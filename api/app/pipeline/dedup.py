"""Normalize + deduplicate discovered businesses.

Match order: normalized domain -> E.164 phone -> token_set_ratio(name) >= 90 with the same
postcode. Matches are transitive (union-find). The merged record starts from the most complete
row, fills gaps from the others, and lists the absorbed rows in `merged_from`.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import phonenumbers
import tldextract
from rapidfuzz import fuzz

from app.schemas import CompanyIn

# Offline public-suffix snapshot: no network fetch at runtime (serverless-friendly).
_tld = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)

# Links that are profiles on someone else's platform, not the business's own site.
NOT_A_WEBSITE = (
    "facebook.com",
    "instagram.com",
    "yelp.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "google.com",
    "goo.gl",
    "linktr.ee",
    "nextdoor.com",
    "tiktok.com",
    "youtube.com",
    "angi.com",
    "homeadvisor.com",
    "bbb.org",
)

_SUFFIXES = {
    "llc", "l l c", "inc", "incorporated", "co", "corp", "corporation", "company", "ltd", "limited",
    "pllc", "pc", "lp", "llp", "the",
}  # fmt: skip


def normalize_domain(url: str | None) -> str | None:
    """'https://WWW.BuckeyeHVAC.com/about' -> 'buckeyehvac.com'. None for non-sites."""
    if not url:
        return None
    url = url.strip()
    if not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.I):
        url = "http://" + url
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    if not host or "." not in host:
        return None
    ext = _tld(host)
    if not ext.domain or not ext.suffix:
        return None
    registered = f"{ext.domain}.{ext.suffix}"
    if registered in NOT_A_WEBSITE:
        return None
    sub = ext.subdomain
    if sub.startswith("www."):
        sub = sub[4:]
    if sub in ("", "www", "m"):
        return registered
    return f"{sub}.{registered}"


def normalize_phone(phone: str | None, region: str | None = "US") -> str | None:
    if not phone:
        return None
    try:
        n = phonenumbers.parse(phone, (region or "US").upper())
    except phonenumbers.NumberParseException:
        return None
    if not phonenumbers.is_possible_number(n):
        return None
    return phonenumbers.format_number(n, phonenumbers.PhoneNumberFormat.E164)


def phone_is_valid(e164: str | None) -> bool | None:
    if not e164:
        return None
    try:
        return phonenumbers.is_valid_number(phonenumbers.parse(e164, None))
    except phonenumbers.NumberParseException:
        return False


def normalize_name(name: str) -> str:
    s = name.lower().replace("&", " ").replace("+", " ")
    s = re.sub(r"[^\w\s]", " ", s)
    words = [w for w in s.split() if w not in _SUFFIXES]
    # Drop a trailing "co" etc. left after punctuation stripping ("Co." -> "co").
    return " ".join(words)


def normalize_postcode(pc: str | None) -> str | None:
    if not pc:
        return None
    pc = pc.strip().upper()
    m = re.match(r"^(\d{5})(?:-\d{4})?$", pc)
    return m.group(1) if m else pc.replace(" ", "")


def normalize(c: CompanyIn, default_region: str | None = "US") -> CompanyIn:
    domain = c.domain or normalize_domain(c.website)
    website = c.website if domain else None
    return c.model_copy(
        update={
            "domain": domain,
            "website": website,
            "phone_e164": c.phone_e164 or normalize_phone(c.phone, c.country or default_region),
            "postcode": normalize_postcode(c.postcode),
        }
    )


def _completeness(c: CompanyIn) -> int:
    fields = (
        c.website, c.phone_e164, c.address, c.city, c.region, c.postcode, c.lat, c.rating,
        c.review_count, c.email, c.start_date, c.place_id,
    )  # fmt: skip
    return sum(v is not None for v in fields)


def _merge(group: list[CompanyIn]) -> CompanyIn:
    group = sorted(group, key=_completeness, reverse=True)
    base = group[0]
    data = base.model_dump()
    for other in group[1:]:
        for k, v in other.model_dump().items():
            if k in ("merged_from", "raw"):
                continue
            if data.get(k) in (None, "", []) and v not in (None, "", []):
                data[k] = v
        data["raw"] = {**other.raw, **data["raw"]}
    data["merged_from"] = [*base.merged_from, *(o.ident() for o in group[1:])]
    return CompanyIn.model_validate(data)


def dedup(companies: list[CompanyIn], default_region: str | None = "US") -> list[CompanyIn]:
    rows = [normalize(c, default_region) for c in companies]
    parent = list(range(len(rows)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    by_domain: dict[str, int] = {}
    by_phone: dict[str, int] = {}
    for i, c in enumerate(rows):
        if c.domain:
            if c.domain in by_domain:
                union(i, by_domain[c.domain])
            else:
                by_domain[c.domain] = i
        if c.phone_e164:
            if c.phone_e164 in by_phone:
                union(i, by_phone[c.phone_e164])
            else:
                by_phone[c.phone_e164] = i

    names = [normalize_name(c.name) for c in rows]
    for i in range(len(rows)):
        for j in range(i + 1, len(rows)):
            if find(i) == find(j):
                continue
            pi, pj = rows[i].postcode, rows[j].postcode
            if not pi or pi != pj:
                continue
            # Two different known domains are two different businesses, whatever the name says.
            if rows[i].domain and rows[j].domain and rows[i].domain != rows[j].domain:
                continue
            if fuzz.token_set_ratio(names[i], names[j]) >= 90:
                union(i, j)

    groups: dict[int, list[CompanyIn]] = {}
    for i, c in enumerate(rows):
        groups.setdefault(find(i), []).append(c)
    return [_merge(g) if len(g) > 1 else g[0] for _, g in sorted(groups.items())]
