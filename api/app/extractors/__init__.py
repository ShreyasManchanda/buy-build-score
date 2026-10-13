"""Deterministic extractors. `run_all(pages)` returns every fact as {signal: Evidence}."""

from __future__ import annotations

from collections.abc import Callable

from app.extractors.base import Evidence, Pages, PageView
from app.extractors.copyright import copyright_year
from app.extractors.founded import founded_year
from app.extractors.people import people
from app.extractors.site import (
    company_email,
    cta,
    forms,
    https,
    mobile_viewport,
    performance,
    social_links,
    street_address,
)
from app.extractors.tech import table_layout, tech_fingerprints
from app.extractors.text_signals import exit_language, family_owned, hiring

__all__ = ["Evidence", "PageView", "Pages", "run_all"]

_PLAIN: list[Callable[[Pages], list[Evidence]]] = [
    family_owned,
    exit_language,
    hiring,
    people,
    tech_fingerprints,
    table_layout,
    mobile_viewport,
    https,
    performance,
    social_links,
    forms,
    cta,
    company_email,
    street_address,
]


def run_all(pages: Pages, current_year: int) -> dict[str, Evidence]:
    facts: dict[str, Evidence] = {}
    for ev in founded_year(pages, current_year) + copyright_year(pages, current_year):
        facts[ev.signal] = ev
    for fn in _PLAIN:
        for ev in fn(pages):
            facts.setdefault(ev.signal, ev)
    return facts
