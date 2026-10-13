"""copyright_year: the last 4-digit year near ©/&copy;/copyright in the footer region."""

from __future__ import annotations

import re

from app.extractors.base import Evidence, Pages, snippet_at

_COPY = re.compile(
    r"(?:©|\(c\)|&copy;|copyright)\s*(?:©\s*)?(?:(?:19|20)\d\d\s*(?:-|–|—|to)\s*)?((?:19|20)\d\d)",
    re.I,
)


def copyright_year(pages: Pages, current_year: int) -> list[Evidence]:
    home = pages.home
    if home is None:
        return []
    for hay in (home.footer_text, home.text):
        found = [m for m in _COPY.finditer(hay) if 1990 <= int(m.group(1)) <= current_year]
        if found:
            m = found[-1]
            y = int(m.group(1))
            return [
                Evidence("copyright_year", y, f"© {y}", home.url, snippet=snippet_at(hay, m.start(), m.end()))
            ]
    return []
