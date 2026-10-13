"""founded_year: JSON-LD foundingDate first, then "since / est. / founded 19xx" text."""

from __future__ import annotations

import re

from app.extractors import jsonld
from app.extractors.base import Evidence, Pages, snippet_at

YEAR = r"(19[0-9]\d|20[0-2]\d)"
# Strong phrasings first; "since" alone is weaker (it also appears in "since 2020 we've added…").
_STRONG = re.compile(
    r"\b(?:founded|established|est\.?|incorporated|in business since|family[- ]owned since|"
    r"family[- ]operated since|serving [^.!?]{0,60}? since|proudly serving since)"
    r"\s*(?:in\s+|:\s*)?" + YEAR + r"\b",
    re.I,
)
_SINCE = re.compile(r"\bsince\s+" + YEAR + r"\b", re.I)


def _valid(year: int, current_year: int) -> bool:
    return 1900 <= year <= current_year


def founded_year(pages: Pages, current_year: int) -> list[Evidence]:
    # 1. schema.org foundingDate
    for p in pages.pages:
        for obj in jsonld.objects(p):
            fd = obj.get("foundingDate")
            m = re.match(r"\s*(\d{4})", str(fd)) if fd else None
            if m and _valid(int(m.group(1)), current_year):
                y = int(m.group(1))
                return [
                    Evidence(
                        "founded_year",
                        y,
                        str(y),
                        p.url,
                        snippet=f'schema.org foundingDate: "{fd}"',
                        extra={"method": "jsonld"},
                    )
                ]

    # 2. text, strong phrasing wins; earliest plausible year within the winning class
    for pattern, method in ((_STRONG, "regex_strong"), (_SINCE, "regex_since")):
        best: tuple[int, str, str] | None = None
        for p in sorted(pages.pages, key=lambda v: v.kind not in ("about", "home")):
            for m in pattern.finditer(p.text):
                y = int(m.group(1))
                if not _valid(y, current_year):
                    continue
                if best is None or y < best[0]:
                    best = (y, p.url, snippet_at(p.text, m.start(), m.end()))
        if best:
            y, url, snip = best
            return [Evidence("founded_year", y, str(y), url, snippet=snip, extra={"method": method})]
    return []
