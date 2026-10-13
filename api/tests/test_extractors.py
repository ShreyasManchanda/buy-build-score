"""Every fixture's hand-written expectations must be met by the deterministic extractors."""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest

from app.extractors import Pages, PageView, run_all
from app.pipeline import score as scoring

from .conftest import FIXTURES

TODAY = date(2026, 10, 13)
CASES = sorted(p.stem.removesuffix(".expected") for p in FIXTURES.glob("*.expected.json"))


def load(case: str) -> tuple[Pages, dict[str, Any]]:
    spec = json.loads((FIXTURES / f"{case}.expected.json").read_text(encoding="utf-8"))
    html = (FIXTURES / f"{case}.html").read_text(encoding="utf-8")
    m = spec["meta"]
    pages = Pages(
        pages=[PageView(m["url"], "home", html)],
        final_scheme=m["final_scheme"],
        tls_ok=m["tls_ok"],
        ttfb_ms=m["ttfb_ms"],
        home_bytes=m["home_bytes"],
        total_bytes=m["home_bytes"],
    )
    return pages, spec


def test_at_least_ten_fixtures() -> None:
    assert len(CASES) >= 10


@pytest.mark.parametrize("case", CASES)
def test_fixture_signals(case: str) -> None:
    pages, spec = load(case)
    facts = run_all(pages, current_year=TODAY.year)
    exp = spec["expect"]
    for key, want in exp.items():
        if key == "founded_method":
            assert facts["founded_year"].extra["method"] == want, case
        elif key == "has_team_page":
            assert facts["people_named"].extra["has_team_page"] is want, case
        elif key == "wordpress_outdated":
            hits = facts["tech_cms"].extra["hits"]
            assert any(h.get("outdated") for h in hits) is want, case
        elif key == "owner_name":
            assert facts["owner_name"].value == want, case
        else:
            assert key in facts, f"{case}: {key} not extracted"
            assert facts[key].value == want, f"{case}: {key} = {facts[key].value!r}, want {want!r}"
    # nobody named -> no owner fact
    if "owner_name" not in exp:
        assert "owner_name" not in facts, f"{case}: unexpected owner {facts.get('owner_name')}"
    # every fact carries a source URL; text snippets are bounded
    for ev in facts.values():
        assert ev.source_url, f"{case}: {ev.signal} has no source"
        assert ev.snippet is None or len(ev.snippet) <= 200


@pytest.mark.parametrize("case", CASES)
def test_fixture_scores_point_at_expected_signals(case: str) -> None:
    pages, spec = load(case)
    facts = run_all(pages, current_year=TODAY.year)
    company = scoring.CompanyFacts(
        name=spec["name"], mode="osm", website_responds=True, home_url=spec["meta"]["url"]
    )
    res = scoring.score(facts, company, "ok", today=TODAY)
    for dim in ("upside", "succession"):
        got = sorted(e.signal for e in res.evidence if e.dimension == dim and e.points > 0)
        assert got == sorted(spec["scores"][f"{dim}_signals"]), f"{case} {dim}: {got}"
    # every evidence row is explainable
    for e in res.evidence:
        assert e.source_url and e.label and e.extractor
    assert 0 <= res.durability <= 100 and 0 <= res.succession <= 100 and 0 <= res.upside <= 100


def test_snippets_are_quotes_from_the_page() -> None:
    pages, _ = load("plumbing_reilly_retiring")
    facts = run_all(pages, current_year=TODAY.year)
    snip = facts["exit_language"].snippet or ""
    assert "retiring" in snip
    assert snip.strip("…") in " ".join(pages.home.text.split())  # type: ignore[union-attr]


def test_no_pages_means_no_facts() -> None:
    assert run_all(Pages(pages=[]), current_year=2026) == {}


def test_founded_year_rejects_future_and_ancient_years() -> None:
    html = "<p>Established 2031. Founded 1850. Since 1999 we have grown.</p>"
    facts = run_all(Pages([PageView("https://x.com/", "home", html)]), current_year=2026)
    assert facts["founded_year"].value == 1999


def test_copyright_range_takes_last_year() -> None:
    html = "<footer>Copyright © 2004–2017 Acme Heating</footer>"
    facts = run_all(Pages([PageView("https://x.com/", "home", html)]), current_year=2026)
    assert facts["copyright_year"].value == 2017


def test_people_regex_ignores_business_words() -> None:
    html = "<p>Owner: Columbus Heating Services. President - Ann Marie Walsh.</p>"
    facts = run_all(Pages([PageView("https://x.com/", "home", html)]), current_year=2026)
    assert facts["people_named"].value == ["Ann Marie Walsh"]


@pytest.mark.parametrize(
    ("html", "want"),
    [
        ("<p>Our business is family run. He also has used vehicles for sale on the lot.</p>", False),
        ("<p>Homes for sale near our company office.</p>", False),
        ("<p>After 30 years the business is for sale; the owner wants a buyer.</p>", True),
        ("<p>Business for sale: owner retiring.</p>", True),
    ],
)
def test_for_sale_must_refer_to_the_business(html: str, want: bool) -> None:
    facts = run_all(Pages([PageView("https://x.com/", "home", html)]), current_year=2026)
    assert facts["exit_language"].value is want
