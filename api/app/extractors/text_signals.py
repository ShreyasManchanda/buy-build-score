"""Keyword signals with negation guards: family_owned, exit_language, hiring."""

from __future__ import annotations

import re

from app import configs
from app.extractors.base import Evidence, Pages, PageView, snippet_at

_NEGATION_BEFORE = re.compile(r"\b(no|not|no longer|never|isn't|is not|aren't|n't)\b[\w\s,'-]{0,20}$", re.I)


def _negated(text: str, start: int) -> bool:
    return bool(_NEGATION_BEFORE.search(text[max(0, start - 30) : start]))


def _compile(patterns: list[str]) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns), re.I)


# ---------------------------------------------------------------- family-owned


def family_owned(pages: Pages) -> list[Evidence]:
    if not pages.pages:
        return []
    cfg = configs.scoring()["dimensions"]["succession"]["signals"]["founder_family_run"]
    pat = _compile(cfg["patterns"])
    for p in pages.pages:
        for m in pat.finditer(p.text):
            if _negated(p.text, m.start()):
                continue
            return [
                Evidence(
                    "family_owned", True, m.group(0).strip(), p.url, snippet_at(p.text, m.start(), m.end())
                )
            ]
    return [
        Evidence(
            "family_owned",
            False,
            "no family/founder language",
            pages.home_url,
            snippet=f"Checked {len(pages.pages)} page(s)",
        )
    ]


# ---------------------------------------------------------------- exit language

# "retirement planning", "succession planning", "retirement community" are services, not exits.
_SERVICE_AFTER = re.compile(
    r"^\s*(?:and\s+\w+\s+)?(?:plan|planning|plans|community|communities|home|account)", re.I
)


def exit_language(pages: Pages) -> list[Evidence]:
    if not pages.pages:
        return []
    cfg = configs.scoring()["dimensions"]["succession"]["signals"]["exit_language"]
    pat = _compile(cfg["patterns"])
    near = _compile([re.escape(w) for w in cfg["near"]])
    negations = _compile([re.escape(n) for n in cfg["negations"]])
    window = int(cfg["window_chars"])
    for p in pages.pages:
        text = p.text
        for m in pat.finditer(text):
            ctx_a, ctx_b = max(0, m.start() - window), min(len(text), m.end() + window)
            ctx = text[ctx_a:ctx_b]
            if not near.search(ctx):
                continue
            if negations.search(text[max(0, m.start() - 30) : m.end() + 5]) or _negated(text, m.start()):
                continue
            # Extend to the end of the word ("retire" inside "retirement") before the service guard.
            end = m.end() + len(re.match(r"\w*", text[m.end() :]).group())  # type: ignore[union-attr]
            if _SERVICE_AFTER.match(text[end : end + 30]):
                continue
            return [
                Evidence(
                    "exit_language",
                    True,
                    text[m.start() : end].strip(),
                    p.url,
                    snippet_at(text, m.start(), end),
                )
            ]
    return [
        Evidence(
            "exit_language",
            False,
            "none found",
            pages.home_url,
            snippet=f"Checked {len(pages.pages)} page(s) for retiring/for sale/succession",
        )
    ]


# ---------------------------------------------------------------- hiring

_HIRING_TEXT = re.compile(
    r"\b(?:we['’]re hiring|we are hiring|now hiring|join our team|job openings|open positions|"
    r"apply (?:now|today|online)|career opportunities)\b",
    re.I,
)
_CAREERS_LINK = re.compile(r"/(?:careers?|jobs?|employment|join-our-team|hiring)(?:[/.?#-]|$)", re.I)


def _careers_link(p: PageView) -> str | None:
    for a in p.tree.css("a[href]"):
        href = a.attributes.get("href") or ""
        if _CAREERS_LINK.search(href):
            return href
    return None


def hiring(pages: Pages) -> list[Evidence]:
    if not pages.pages:
        return []
    careers = pages.of_kind("careers")
    if careers:
        c = careers[0]
        return [Evidence("hiring", True, "careers page", c.url, snippet=f"Careers page found: {c.url}"[:200])]
    for p in pages.pages:
        for m in _HIRING_TEXT.finditer(p.text):
            if _negated(p.text, m.start()):
                continue
            return [Evidence("hiring", True, m.group(0), p.url, snippet_at(p.text, m.start(), m.end()))]
    home = pages.home
    link = _careers_link(home) if home else None
    if link and home:
        return [Evidence("hiring", True, "careers link", home.url, snippet=f"Link to {link}"[:200])]
    return [
        Evidence(
            "hiring",
            False,
            "no careers page or hiring text",
            pages.home_url,
            snippet=f"Checked {len(pages.pages)} page(s)",
        )
    ]
