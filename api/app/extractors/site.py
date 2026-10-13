"""Site-structure signals: mobile viewport, HTTPS/TLS, speed, social links, CTAs, forms, email, address."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from app import configs
from app.extractors import jsonld
from app.extractors.base import HTTP_CONFIDENCE, Evidence, Pages, snippet_at
from app.pipeline.dedup import normalize_domain


def mobile_viewport(pages: Pages) -> list[Evidence]:
    home = pages.home
    if home is None:
        return []
    meta = home.tree.css_first('meta[name="viewport" i]')
    content = (meta.attributes.get("content") or "") if meta else ""
    return [
        Evidence(
            "mobile_viewport",
            bool(meta),
            content or "no <meta name=viewport>",
            home.url,
            snippet=f'<meta name="viewport" content="{content}">'
            if meta
            else "No viewport meta tag on homepage",
        )
    ]


def https(pages: Pages) -> list[Evidence]:
    if pages.final_scheme is None:
        return []
    ok = pages.final_scheme == "https" and pages.tls_ok is not False
    if pages.tls_ok is False:
        disp, snip = (
            "certificate failed",
            "HTTPS handshake failed certificate verification; site read over HTTP",
        )
    elif ok:
        disp, snip = "HTTPS", f"Final URL is HTTPS: {pages.home_url}"
    else:
        disp, snip = "HTTP only", f"Final URL is plain HTTP: {pages.home_url}"
    return [
        Evidence(
            "https",
            ok,
            disp,
            pages.home_url,
            snippet=snip[:200],
            extractor="http",
            confidence=HTTP_CONFIDENCE,
        )
    ]


def performance(pages: Pages) -> list[Evidence]:
    if pages.ttfb_ms is None:
        return []
    return [
        Evidence(
            "ttfb_ms",
            pages.ttfb_ms,
            f"{pages.ttfb_ms} ms TTFB",
            pages.home_url,
            snippet=f"Time to first byte {pages.ttfb_ms} ms; homepage HTML {pages.home_bytes // 1024} KB",
            extractor="http",
            confidence=HTTP_CONFIDENCE,
            extra={"home_bytes": pages.home_bytes},
        ),
    ]


def social_links(pages: Pages) -> list[Evidence]:
    home = pages.home
    if home is None:
        return []
    domains = configs.scoring()["dimensions"]["upside"]["signals"]["no_social_links"]["domains"]
    found: dict[str, str] = {}
    for p in pages.pages:
        for a in p.tree.css("a[href]"):
            href = a.attributes.get("href") or ""
            host = (urlsplit(href).hostname or "").lower()
            for d in domains:
                if host == d or host.endswith("." + d):
                    found.setdefault(d.split(".")[0], href)
    names = sorted(found)
    return [
        Evidence(
            "social_links",
            names,
            ", ".join(names) if names else "none",
            home.url,
            snippet=("Links: " + ", ".join(found[n] for n in names))[:200]
            if names
            else "No social profile links",
        )
    ]


_QUOTE_WORDS = re.compile(r"quote|estimate|book|schedule|appointment|request service", re.I)


def forms(pages: Pages) -> list[Evidence]:
    """quote_form (a <form> about quotes/booking) and has_form (any form)."""
    if not pages.pages:
        return []
    any_form_url: str | None = None
    for p in pages.pages:
        for f in p.tree.css("form"):
            # Skip site-search forms.
            if f.css_first('input[type="search"]') or (f.attributes.get("role") or "") == "search":
                continue
            any_form_url = any_form_url or p.url
            blob = " ".join(
                [f.text(separator=" "), f.attributes.get("action") or "", f.attributes.get("id") or ""]
                + [
                    (i.attributes.get("value") or "")
                    + " "
                    + (i.attributes.get("placeholder") or "")
                    + " "
                    + (i.attributes.get("name") or "")
                    for i in f.css("input, button, textarea, select")
                ]
            )
            m = _QUOTE_WORDS.search(blob)
            if m:
                return [
                    Evidence(
                        "quote_form", True, "quote/booking form", p.url, snippet=" ".join(blob.split())[:200]
                    ),
                    Evidence("has_form", True, "form", p.url),
                ]
    return [
        Evidence(
            "quote_form",
            False,
            "no quote/booking form",
            pages.home_url,
            snippet=f"Checked forms on {len(pages.pages)} page(s)",
        ),
        Evidence(
            "has_form",
            any_form_url is not None,
            "form" if any_form_url else "no form",
            any_form_url or pages.home_url,
        ),
    ]


def cta(pages: Pages) -> list[Evidence]:
    """tel: / mailto: links (phone_only_cta is decided in scoring with has_form)."""
    home = pages.home
    if home is None:
        return []
    tel = mail = None
    for p in pages.pages:
        tel = tel or p.tree.css_first('a[href^="tel:" i]')
        mail = mail or p.tree.css_first('a[href^="mailto:" i]')
    tel_href = tel.attributes.get("href") if tel else None
    mail_href = mail.attributes.get("href") if mail else None
    return [
        Evidence("tel_link", bool(tel), tel_href or "none", home.url),
        Evidence("mailto_link", bool(mail), mail_href or "none", home.url),
    ]


_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_EMAIL_JUNK = re.compile(r"\.(png|jpe?g|gif|webp|svg)$|example\.|sentry|wixpress|godaddy|@domain\.", re.I)


def company_email(pages: Pages) -> list[Evidence]:
    """A company-level email from mailto: links or the contact page. Same-domain addresses preferred."""
    if not pages.pages:
        return []
    site = normalize_domain(pages.home_url)
    candidates: list[tuple[int, str, str, str]] = []
    for p in sorted(pages.pages, key=lambda v: v.kind != "contact"):
        for a in p.tree.css('a[href^="mailto:" i]'):
            addr = (a.attributes.get("href") or "")[7:].split("?")[0].strip()
            if _EMAIL.fullmatch(addr) and not _EMAIL_JUNK.search(addr):
                candidates.append((0, addr.lower(), p.url, f"mailto:{addr}"))
        for m in _EMAIL.finditer(p.text):
            addr = m.group(0)
            if not _EMAIL_JUNK.search(addr):
                candidates.append((1, addr.lower(), p.url, snippet_at(p.text, m.start(), m.end())))
    if not candidates:
        return []
    candidates.sort(key=lambda c: (normalize_domain("http://" + c[1].split("@")[1]) != site, c[0]))
    _, addr, url, snip = candidates[0]
    return [Evidence("email", addr, addr, url, snippet=snip)]


def street_address(pages: Pages) -> list[Evidence]:
    """schema.org PostalAddress.streetAddress — used for 'operating, fixed location' when discovery lacks one."""
    for p in pages.pages:
        for obj in jsonld.objects(p):
            if obj.get("@type") == "PostalAddress" or "streetAddress" in obj:
                street = obj.get("streetAddress")
                if isinstance(street, str) and re.search(r"\d", street):
                    parts = [
                        street,
                        obj.get("addressLocality"),
                        obj.get("addressRegion"),
                        obj.get("postalCode"),
                    ]
                    addr = ", ".join(str(x) for x in parts if x)
                    return [
                        Evidence(
                            "street_address", addr, addr, p.url, snippet=f"schema.org address: {addr}"[:200]
                        )
                    ]
    return []
