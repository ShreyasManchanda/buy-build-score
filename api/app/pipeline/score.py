"""Scoring: facts -> three 0-100 sub-scores, coverage, and one evidence row per known signal.

Pure and deterministic. All thresholds come from scoring.yaml. Rules:
- points x confidence (weak evidence counts less);
- a signal we couldn't evaluate scores 0, is listed as missing, and lowers coverage;
- OSM/CSV mode has no reviews/rating/status, so durability is re-normalised over 50 raw points;
- composite + tier are computed from weights at read time (never stored).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

from app import configs
from app.extractors.base import Evidence
from app.pipeline.dedup import normalize_name

SIGNALS: dict[str, list[str]] = {
    "durability": [
        "years_in_business",
        "review_volume",
        "rating",
        "recent_activity",
        "operating_fixed_location",
    ],
    "succession": [
        "long_tenure",
        "founder_family_run",
        "single_leader",
        "stale_copyright",
        "not_hiring",
        "exit_language",
    ],
    "upside": [
        "no_booking_or_quote",
        "slow_site",
        "no_live_chat",
        "no_https",
        "not_mobile_ready",
        "outdated_stack",
        "no_analytics",
        "phone_only_cta",
        "no_social_links",
    ],
}
PLACES_ONLY = {"review_volume", "rating", "recent_activity"}

LABELS = {
    "years_in_business": "Years in business",
    "review_volume": "Review volume",
    "rating": "Rating",
    "recent_activity": "Recent reviews",
    "operating_fixed_location": "Operating, fixed location",
    "long_tenure": "Long tenure",
    "founder_family_run": "Founder / family-run",
    "single_leader": "Single named leader",
    "stale_copyright": "Stale web presence",
    "not_hiring": "Not hiring",
    "exit_language": "Exit language",
    "no_booking_or_quote": "No online booking / quote",
    "slow_site": "Slow site",
    "no_live_chat": "No live chat",
    "no_https": "No HTTPS",
    "not_mobile_ready": "Not mobile-ready",
    "outdated_stack": "Outdated stack",
    "no_analytics": "No analytics",
    "phone_only_cta": "Phone-only call to action",
    "no_social_links": "No social links",
}

Mode = Literal["places", "osm", "csv", "demo"]


@dataclass
class CompanyFacts:
    """Discovery-level facts about a company (not from its website)."""

    name: str
    mode: str = "osm"
    osm_id: str | None = None
    osm_start_year: int | None = None
    place_id: str | None = None
    rating: float | None = None
    review_count: int | None = None
    business_status: str | None = None
    newest_review_at: datetime | None = None
    street_address: str | None = None
    website_responds: bool = False
    home_url: str | None = None
    pagespeed: int | None = None


@dataclass
class ScoredEvidence:
    dimension: str
    signal: str
    label: str
    value: str
    points: float
    max_points: float
    confidence: float
    source_url: str | None
    snippet: str | None
    extractor: str

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


@dataclass
class ScoreResult:
    durability: int
    succession: int
    upside: int
    coverage: float
    durability_mode: Literal["full", "site_only"]
    evidence: list[ScoredEvidence] = field(default_factory=list)
    missing: list[dict[str, Any]] = field(default_factory=list)
    founded_year: int | None = None
    owner_name: str | None = None

    def top_evidence(self, n: int = 3) -> list[str]:
        rows = sorted((e for e in self.evidence if e.points > 0), key=lambda e: -e.points)
        return [chip(e) for e in rows[:n]]


# ---------------------------------------------------------------- helpers


def _cfg() -> dict[str, Any]:
    return configs.scoring()


def round_half_up(x: float) -> int:
    """Same rounding as JavaScript's Math.round, so API and browser agree on every composite."""
    return math.floor(x + 0.5)


def _conf(extractor: str) -> float:
    return float(_cfg()["confidence"].get(extractor, 0.9))


def _band(value: float, bands: list[dict[str, Any]]) -> float:
    for b in bands:
        if value >= b["min"]:
            return float(b["points"])
    return 0.0


def _band_max(value: float, bands: list[dict[str, Any]]) -> float:
    for b in bands:
        if value <= b["max"]:
            return float(b["points"])
    return 0.0


def _max_points(dimension: str, signal: str) -> float:
    spec = _cfg()["dimensions"][dimension]["signals"][signal]
    if "points" in spec:
        return float(spec["points"])
    for key in ("bands", "bands_years_old", "bands_max_days", "pagespeed_bands"):
        if key in spec:
            return max(float(b["points"]) for b in spec[key])
    return 0.0


def osm_url(osm_id: str | None) -> str | None:
    return f"https://www.openstreetmap.org/{osm_id}" if osm_id else None


def maps_url(place_id: str | None) -> str | None:
    return f"https://www.google.com/maps/place/?q=place_id:{place_id}" if place_id else None


def chip(e: ScoredEvidence) -> str:
    """Short evidence chip text for tables/CSV."""
    v = e.value
    return {
        "years_in_business": f"Since {v.split()[0]}",
        "long_tenure": f"{v} in business",
        "stale_copyright": f"{v} footer",
        "exit_language": f"“{v}”",
        "founder_family_run": f"“{v}”" if not v.startswith("owner") else v,
        "review_volume": f"{v} reviews",
        "rating": f"★ {v}",
    }.get(e.signal, e.label)


# ---------------------------------------------------------------- scorer


def score(
    facts: dict[str, Evidence],
    company: CompanyFacts,
    crawl_status: str,
    today: date | None = None,
) -> ScoreResult:
    today = today or datetime.now(UTC).date()
    year = today.year
    cfg = _cfg()
    dims = cfg["dimensions"]
    places_mode = company.mode == "places"
    rows: list[ScoredEvidence] = []
    known: set[str] = set()

    def add(
        dim: str,
        sig: str,
        value: str,
        raw_points: float,
        ev: Evidence | None,
        *,
        extractor: str | None = None,
        url: str | None = None,
        snippet: str | None = None,
    ) -> None:
        ex = extractor or (ev.extractor if ev else "rule")
        conf = ev.confidence if ev and extractor is None else _conf(ex)
        rows.append(
            ScoredEvidence(
                dimension=dim,
                signal=sig,
                label=LABELS[sig],
                value=value,
                points=round(raw_points * conf, 1),
                max_points=_max_points(dim, sig),
                confidence=round(conf, 2),
                source_url=url if url is not None else (ev.source_url if ev else None),
                snippet=(snippet if snippet is not None else (ev.snippet if ev else None) or "")[:200]
                or None,
                extractor=ex,
            )
        )
        known.add(sig)

    # ---- founding year: rule (jsonld/regex) > osm start_date > llm
    founded_ev = facts.get("founded_year")
    founded: int | None = None
    founded_src: tuple[Evidence | None, str | None, str | None, str | None] = (None, None, None, None)
    if founded_ev and founded_ev.extractor == "rule":
        founded = int(founded_ev.value)
        founded_src = (founded_ev, None, None, None)
    elif company.osm_start_year:
        founded = company.osm_start_year
        founded_src = (None, "osm", osm_url(company.osm_id), f"OpenStreetMap start_date={founded}")
    elif founded_ev:
        founded = int(founded_ev.value)
        founded_src = (founded_ev, None, None, None)

    # ================================================================ durability
    d = dims["durability"]["signals"]
    if founded:
        yrs = max(0, year - founded)
        ev, ex, url, snip = founded_src
        add(
            "durability",
            "years_in_business",
            f"{founded} ({yrs} yrs)",
            _band(yrs, d["years_in_business"]["bands"]),
            ev,
            extractor=ex,
            url=url,
            snippet=snip,
        )
    if places_mode:
        purl = maps_url(company.place_id)
        if company.review_count is not None:
            add(
                "durability",
                "review_volume",
                str(company.review_count),
                _band(company.review_count, d["review_volume"]["bands"]),
                None,
                extractor="places",
                url=purl,
                snippet=f"Google userRatingCount: {company.review_count}",
            )
        if company.rating is not None:
            add(
                "durability",
                "rating",
                f"{company.rating:.1f}",
                _band(company.rating, d["rating"]["bands"]),
                None,
                extractor="places",
                url=purl,
                snippet=f"Google rating: {company.rating:.1f}",
            )
        if company.newest_review_at is not None:
            days = (today - company.newest_review_at.date()).days
            add(
                "durability",
                "recent_activity",
                f"{days} days ago",
                _band_max(days, d["recent_activity"]["bands_max_days"]),
                None,
                extractor="places",
                url=purl,
                snippet=f"Newest Google review {company.newest_review_at.date().isoformat()}",
            )
        if company.business_status is not None:
            operating = company.business_status == "OPERATIONAL" and bool(company.street_address)
            add(
                "durability",
                "operating_fixed_location",
                f"{company.business_status.title()}"
                + (" · street address" if company.street_address else ""),
                d["operating_fixed_location"]["points"] if operating else 0,
                None,
                extractor="places",
                url=purl,
                snippet=f"businessStatus={company.business_status}; {company.street_address or 'no street address'}",
            )
    else:
        addr_ev = facts.get("street_address")
        street = company.street_address or (addr_ev.value if addr_ev else None)
        operating = bool(street) and company.website_responds
        why = []
        why.append(f"address: {street}" if street else "no street address")
        why.append("website responds" if company.website_responds else "website did not respond")
        from_osm = bool(company.street_address and company.osm_id)
        url = osm_url(company.osm_id) if from_osm else (addr_ev.source_url if addr_ev else company.home_url)
        add(
            "durability",
            "operating_fixed_location",
            "yes" if operating else "no",
            d["operating_fixed_location"]["points"] if operating else 0,
            None,
            extractor="osm" if from_osm else "rule",
            url=url or company.home_url,
            snippet="; ".join(why),
        )

    raw_d = sum(r.points for r in rows if r.dimension == "durability")
    if places_mode:
        durability = min(100, round_half_up(raw_d))
    else:
        durability = min(100, round_half_up(raw_d / float(dims["durability"]["osm_mode_max_raw"]) * 100))

    # ================================================================ succession
    s = dims["succession"]["signals"]
    if founded:
        yrs = max(0, year - founded)
        ev, ex, url, snip = founded_src
        add(
            "succession",
            "long_tenure",
            f"{yrs} yrs",
            _band(yrs, s["long_tenure"]["bands"]),
            ev,
            extractor=ex,
            url=url,
            snippet=snip,
        )

    owner_ev = facts.get("owner_name")
    owner = str(owner_ev.value) if owner_ev else None
    fam = facts.get("family_owned")
    if fam is not None and fam.value:
        add("succession", "founder_family_run", fam.display, s["founder_family_run"]["points"], fam)
    elif owner and _surname_in_name(owner, company.name):
        add(
            "succession",
            "founder_family_run",
            f"owner surname “{owner.split()[-1]}” in name",
            s["founder_family_run"]["points"],
            owner_ev,
        )
    elif fam is not None:
        add("succession", "founder_family_run", "not stated", 0, fam)

    ppl = facts.get("people_named")
    if ppl is not None:
        names: list[str] = list(ppl.value)
        team = bool(ppl.extra.get("has_team_page"))
        single = len(names) == 1 and not team
        val = (names[0] if single else (f"{len(names)} people named" if names else "nobody named")) + (
            " · team page" if team else ""
        )
        add("succession", "single_leader", val, s["single_leader"]["points"] if single else 0, ppl)

    cy = facts.get("copyright_year")
    if cy is not None:
        age = year - int(cy.value)
        add(
            "succession",
            "stale_copyright",
            f"© {cy.value}",
            _band(age, s["stale_copyright"]["bands_years_old"]),
            cy,
        )

    hire = facts.get("hiring")
    if hire is not None:
        add(
            "succession",
            "not_hiring",
            "not hiring" if not hire.value else f"hiring ({hire.display})",
            0 if hire.value else s["not_hiring"]["points"],
            hire,
        )

    ex_ev = facts.get("exit_language")
    if ex_ev is not None:
        add(
            "succession",
            "exit_language",
            ex_ev.display if ex_ev.value else "none",
            s["exit_language"]["points"] if ex_ev.value else 0,
            ex_ev,
        )

    succession = min(100, round_half_up(sum(r.points for r in rows if r.dimension == "succession")))

    # ================================================================ upside
    u = dims["upside"]["signals"]
    booking, chat = facts.get("tech_booking"), facts.get("tech_chat")
    analytics, legacy, cms = facts.get("tech_analytics"), facts.get("tech_legacy"), facts.get("tech_cms")
    qform = facts.get("quote_form")
    if booking is not None and qform is not None:
        has = bool(booking.value) or bool(qform.value)
        src = booking if booking.value else qform
        add(
            "upside",
            "no_booking_or_quote",
            booking.display if booking.value else ("quote form" if qform.value else "none"),
            0 if has else u["no_booking_or_quote"]["points"],
            src,
        )

    ttfb = facts.get("ttfb_ms")
    if company.pagespeed is not None:
        add(
            "upside",
            "slow_site",
            f"PageSpeed {company.pagespeed}",
            _band_max(company.pagespeed, u["slow_site"]["pagespeed_bands"]),
            None,
            extractor="http",
            snippet=f"PageSpeed Insights mobile performance {company.pagespeed}/100",
        )
    elif ttfb is not None:
        fb = u["slow_site"]["fallback"]
        home_bytes = int(ttfb.extra.get("home_bytes", 0))
        slow = int(ttfb.value) > fb["ttfb_ms_over"] or home_bytes > fb["page_bytes_over"]
        add("upside", "slow_site", ttfb.display, fb["points"] if slow else 0, ttfb)

    if chat is not None:
        add("upside", "no_live_chat", chat.display, 0 if chat.value else u["no_live_chat"]["points"], chat)

    sec = facts.get("https")
    if sec is not None:
        add("upside", "no_https", sec.display, 0 if sec.value else u["no_https"]["points"], sec)

    vp = facts.get("mobile_viewport")
    if vp is not None:
        add(
            "upside",
            "not_mobile_ready",
            "viewport set" if vp.value else "no viewport meta",
            0 if vp.value else u["not_mobile_ready"]["points"],
            vp,
        )

    tbl = facts.get("table_layout")
    if legacy is not None or tbl is not None or cms is not None:
        reasons: list[str] = []
        src_ev: Evidence | None = None
        if legacy is not None and legacy.value:
            reasons.append(legacy.display)
            src_ev = legacy
        if cms is not None:
            for h in cms.extra.get("hits", []):
                if h.get("outdated"):
                    reasons.append(f"WordPress {h['version']}")
                    src_ev = src_ev or cms
        if tbl is not None and tbl.value:
            reasons.append("table layout")
            src_ev = src_ev or tbl
        add(
            "upside",
            "outdated_stack",
            ", ".join(reasons) if reasons else "current",
            u["outdated_stack"]["points"] if reasons else 0,
            src_ev or legacy or tbl or cms,
        )

    if analytics is not None:
        add(
            "upside",
            "no_analytics",
            analytics.display,
            0 if analytics.value else u["no_analytics"]["points"],
            analytics,
        )

    tel, mail, has_form = facts.get("tel_link"), facts.get("mailto_link"), facts.get("has_form")
    if tel is not None and mail is not None and has_form is not None:
        phone_only = bool(tel.value) and not mail.value and not has_form.value
        val = (
            "tel: only"
            if phone_only
            else ", ".join(
                x for x, ok in (("tel:", tel.value), ("mailto:", mail.value), ("form", has_form.value)) if ok
            )
            or "no CTA links"
        )
        add(
            "upside",
            "phone_only_cta",
            val,
            u["phone_only_cta"]["points"] if phone_only else 0,
            tel,
            snippet=f"tel: {'yes' if tel.value else 'no'} · mailto: {'yes' if mail.value else 'no'} · "
            f"form: {'yes' if has_form.value else 'no'}",
        )

    soc = facts.get("social_links")
    if soc is not None:
        add("upside", "no_social_links", soc.display, 0 if soc.value else u["no_social_links"]["points"], soc)

    upside = min(100, round_half_up(sum(r.points for r in rows if r.dimension == "upside")))

    # ================================================================ coverage + missing
    applicable = [
        (dim, sig) for dim, sigs in SIGNALS.items() for sig in sigs if places_mode or sig not in PLACES_ONLY
    ]
    missing = [
        {"dimension": dim, "signal": sig, "label": LABELS[sig], "max_points": _max_points(dim, sig)}
        for dim, sig in applicable
        if sig not in known
    ]
    coverage = round(sum(1 for _, sig in applicable if sig in known) / len(applicable), 2)
    del crawl_status  # status is reflected through which facts exist

    return ScoreResult(
        durability=durability,
        succession=succession,
        upside=upside,
        coverage=coverage,
        durability_mode="full" if places_mode else "site_only",
        evidence=rows,
        missing=missing,
        founded_year=founded,
        owner_name=owner,
    )


def _surname_in_name(owner: str, business: str) -> bool:
    surname = re.sub(r"[^a-z]", "", owner.split()[-1].lower())
    return len(surname) >= 3 and surname in normalize_name(business).split()


# ---------------------------------------------------------------- composite + tier (mirrored in web/lib/score.ts)


def weights_for(preset: str) -> tuple[float, float, float]:
    p = _cfg()["presets"].get(preset) or _cfg()["presets"][_cfg()["default_preset"]]
    return float(p["durability"]), float(p["succession"]), float(p["upside"])


def composite(d: int, s: int, u: int, wd: float, ws: float, wu: float) -> int:
    total = wd + ws + wu
    if total <= 0:
        return 0
    return round_half_up((wd * d + ws * s + wu * u) / total)


def tier(comp: int, durability: int, coverage: float) -> tuple[str, str | None]:
    """Returns (tier, cap_reason). Guardrails cap at B: durability floor, thin data."""
    cfg = _cfg()
    t = "A" if comp >= cfg["tiers"]["A"] else "B" if comp >= cfg["tiers"]["B"] else "C"
    if t == "A":
        if coverage < cfg["guardrails"]["min_coverage_for_A"]:
            return "B", "thin_data"
        if durability < cfg["guardrails"]["durability_floor"]:
            return "B", "durability_floor"
    return t, None


def is_thin(coverage: float) -> bool:
    return coverage < float(_cfg()["guardrails"]["min_coverage_for_A"])
