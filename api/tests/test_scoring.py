from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.extractors import Evidence, Pages, PageView, run_all
from app.pipeline import score as s

TODAY = date(2026, 10, 13)


def ev(signal: str, value: object, extractor: str = "rule", conf: float = 0.9, **extra: object) -> Evidence:
    return Evidence(signal, value, str(value), "https://x.com/", "snip", extractor, conf, dict(extra))


def site_facts(**overrides: Evidence) -> dict[str, Evidence]:
    """A crawled site with every upside capability present (so upside = 0) unless overridden."""
    base = {
        "tech_booking": ev("tech_booking", ["Calendly"]),
        "tech_chat": ev("tech_chat", ["Tidio"]),
        "tech_analytics": ev("tech_analytics", ["GA4"]),
        "tech_legacy": ev("tech_legacy", []),
        "tech_cms": ev("tech_cms", [], hits=[]),
        "table_layout": ev("table_layout", False),
        "quote_form": ev("quote_form", True),
        "has_form": ev("has_form", True),
        "tel_link": ev("tel_link", True),
        "mailto_link": ev("mailto_link", True),
        "https": ev("https", True, "http", 0.95),
        "mobile_viewport": ev("mobile_viewport", True),
        "ttfb_ms": ev("ttfb_ms", 200, "http", 0.95, home_bytes=10_000),
        "social_links": ev("social_links", ["facebook"]),
        "family_owned": ev("family_owned", False),
        "exit_language": ev("exit_language", False),
        "hiring": ev("hiring", True),
        "people_named": ev("people_named", [], has_team_page=False),
    }
    base.update(overrides)
    return base


def test_osm_mode_renormalises_durability_over_50() -> None:
    facts = site_facts(founded_year=ev("founded_year", 1980))
    c = s.CompanyFacts(
        name="Acme", mode="osm", osm_id="node/1", street_address="1 Main St", website_responds=True
    )
    r = s.score(facts, c, "ok", today=TODAY)
    # 35*0.9 (46 yrs) + 15*0.85 (OSM address + responds) = 44.25 raw of 50 -> 88.5 -> 89 (half-up)
    assert r.durability == 89
    assert r.durability_mode == "site_only"
    assert {m["signal"] for m in r.missing}.isdisjoint({"review_volume", "rating", "recent_activity"})


def test_places_mode_uses_all_five_durability_signals() -> None:
    facts = site_facts(founded_year=ev("founded_year", 1990))
    c = s.CompanyFacts(
        name="Acme",
        mode="places",
        place_id="ChIJ1",
        rating=4.7,
        review_count=212,
        business_status="OPERATIONAL",
        street_address="1 Main St",
        newest_review_at=datetime(2026, 9, 30, tzinfo=UTC),
    )
    r = s.score(facts, c, "ok", today=TODAY)
    # 35*.9 + 25*.95 + 15*.95 + 10*.95 + 15*.95 = 31.5 + 61.75 = 93.25 -> 93
    assert r.durability == 93 and r.durability_mode == "full"
    places_rows = [e for e in r.evidence if e.extractor == "places"]
    assert len(places_rows) == 4
    assert all(e.source_url == "https://www.google.com/maps/place/?q=place_id:ChIJ1" for e in places_rows)


def test_subscores_are_capped_at_100() -> None:
    facts = site_facts(
        founded_year=ev("founded_year", 1950, conf=1.0),
        family_owned=ev("family_owned", True, conf=1.0),
        people_named=ev("people_named", ["Tom Reilly"], conf=1.0, has_team_page=False),
        copyright_year=ev("copyright_year", 2015, conf=1.0),
        hiring=ev("hiring", False, conf=1.0),
        exit_language=ev("exit_language", True, conf=1.0),
    )
    r = s.score(facts, s.CompanyFacts(name="Acme"), "ok", today=TODAY)
    assert r.succession == 100  # 25+20+15+15+10+15 = 100 exactly at full confidence
    for e in r.evidence:
        assert e.points <= e.max_points


def test_confidence_scales_points() -> None:
    weak = s.score(
        site_facts(founded_year=ev("founded_year", 1990, "llm", 0.7)),
        s.CompanyFacts(name="A"),
        "ok",
        today=TODAY,
    )
    strong = s.score(
        site_facts(founded_year=ev("founded_year", 1990)), s.CompanyFacts(name="A"), "ok", today=TODAY
    )
    w = next(e for e in weak.evidence if e.signal == "years_in_business")
    st = next(e for e in strong.evidence if e.signal == "years_in_business")
    assert (w.points, st.points) == (24.5, 31.5)
    assert w.extractor == "llm" and w.confidence == 0.7


def test_rule_founded_year_beats_osm_beats_llm() -> None:
    c = s.CompanyFacts(name="A", osm_id="node/9", osm_start_year=1975)
    r1 = s.score(site_facts(founded_year=ev("founded_year", 1980)), c, "ok", today=TODAY)
    r2 = s.score(site_facts(founded_year=ev("founded_year", 1999, "llm", 0.7)), c, "ok", today=TODAY)
    assert r1.founded_year == 1980 and r2.founded_year == 1975
    osm_row = next(e for e in r2.evidence if e.signal == "years_in_business")
    assert osm_row.extractor == "osm" and osm_row.source_url == "https://www.openstreetmap.org/node/9"


def test_unreachable_site_is_thin_and_tier_capped() -> None:
    r = s.score({}, s.CompanyFacts(name="Ghost", mode="osm"), "unreachable", today=TODAY)
    assert r.coverage < 0.4 and s.is_thin(r.coverage)
    assert r.upside == 0 and r.succession == 0  # missing signals score 0, never guessed
    assert len(r.missing) == 16  # 17 OSM-mode signals, only operating_fixed_location known
    assert s.tier(95, 90, r.coverage) == ("B", "thin_data")


def test_coverage_counts_known_signals_over_applicable() -> None:
    r = s.score(site_facts(), s.CompanyFacts(name="A", mode="osm"), "ok", today=TODAY)
    # known: operating + 4 succession text signals (no founded/copyright) + 9 upside = 14 of 17
    assert r.coverage == round(14 / 17, 2)


@pytest.mark.parametrize(
    ("comp", "d", "cov", "want"),
    [
        (70, 80, 0.9, ("A", None)),
        (69, 80, 0.9, ("B", None)),
        (50, 80, 0.9, ("B", None)),
        (49, 80, 0.9, ("C", None)),
        (85, 29, 0.9, ("B", "durability_floor")),
        (85, 30, 0.9, ("A", None)),
        (85, 80, 0.39, ("B", "thin_data")),
        (40, 10, 0.1, ("C", None)),  # caps only lower A
    ],
)
def test_tier_bands_and_guardrails(comp: int, d: int, cov: float, want: tuple[str, str | None]) -> None:
    assert s.tier(comp, d, cov) == want


def test_preset_weights_and_composite() -> None:
    assert s.weights_for("searcher") == (40, 40, 20)
    assert s.weights_for("sdr") == (25, 10, 65)
    assert s.weights_for("caprae") == (35, 30, 35)
    assert s.weights_for("nonsense") == (40, 40, 20)
    d, su, u = 80, 60, 40
    assert s.composite(d, su, u, *s.weights_for("searcher")) == 64  # (3200+2400+800)/100
    assert s.composite(d, su, u, *s.weights_for("sdr")) == 52  # (2000+600+2600)/100
    assert s.composite(d, su, u, 0, 0, 0) == 0
    assert s.composite(1, 0, 0, 1, 1, 0) == 1  # 0.5 rounds half-up, like Math.round


def test_owner_surname_in_business_name_counts_as_founder_run() -> None:
    facts = site_facts(owner_name=ev("owner_name", "Tom Reilly"))
    r = s.score(facts, s.CompanyFacts(name="Reilly Plumbing Co."), "ok", today=TODAY)
    row = next(e for e in r.evidence if e.signal == "founder_family_run")
    assert row.points == 18.0 and "Reilly" in row.value


def test_slow_site_from_ttfb_or_bytes_and_pagespeed_overrides() -> None:
    slow = site_facts(ttfb_ms=ev("ttfb_ms", 1600, "http", 0.95, home_bytes=1000))
    heavy = site_facts(ttfb_ms=ev("ttfb_ms", 100, "http", 0.95, home_bytes=3_500_000))
    for facts in (slow, heavy):
        r = s.score(facts, s.CompanyFacts(name="A"), "ok", today=TODAY)
        assert next(e for e in r.evidence if e.signal == "slow_site").points == 14.2
    r = s.score(site_facts(), s.CompanyFacts(name="A", pagespeed=62), "ok", today=TODAY)
    assert next(e for e in r.evidence if e.signal == "slow_site").points == 7.6  # 8 * 0.95


def test_top_evidence_chips_rank_by_points() -> None:
    facts = site_facts(
        founded_year=ev("founded_year", 1979),
        copyright_year=ev("copyright_year", 2018),
        tech_booking=ev("tech_booking", []),
        quote_form=ev("quote_form", False),
    )
    r = s.score(facts, s.CompanyFacts(name="A"), "ok", today=TODAY)
    assert r.top_evidence() == ["Since 1979", "47 yrs in business", "No online booking / quote"]


def test_end_to_end_fixture_scores_are_stable() -> None:
    from .conftest import FIXTURES

    html = (FIXTURES / "hvac_buckeye.html").read_text(encoding="utf-8")
    pages = Pages([PageView("http://buckeyehvac.com/", "home", html)], final_scheme="http", ttfb_ms=420)
    facts = run_all(pages, 2026)
    c = s.CompanyFacts(
        name="Buckeye Heating & Cooling",
        mode="osm",
        osm_id="node/1001",
        street_address="1450 Parsons Ave",
        website_responds=True,
    )
    r = s.score(facts, c, "ok", today=TODAY)
    # D: (31.5 + 12.75) / 50 -> 89 ; S: 22.5+18+13.5+13.5+9 = 76.5 -> 77 ; U: 18+9*5+4.5+9.5 -> see below
    assert (r.durability, r.succession) == (89, 77)
    assert r.upside == 77  # 18 + 9 + 9.5 + 9 + 9 + 9 + 9 + 4.5 = 77.0
    comp = s.composite(r.durability, r.succession, r.upside, *s.weights_for("searcher"))
    assert s.tier(comp, r.durability, r.coverage) == ("A", None)
