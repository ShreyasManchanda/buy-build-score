"""DB rows -> API schemas. One place, so the stream, the list and the drawer always agree."""

from __future__ import annotations

from collections.abc import Iterable

from app import models
from app.pipeline import score as scoring
from app.schemas import EvidenceOut, LeadDetail, LeadOut, MissingSignal, Scores


def weights(
    preset: str, wd: float | None = None, ws: float | None = None, wu: float | None = None
) -> tuple[float, float, float]:
    d, s, u = scoring.weights_for(preset)
    return (wd if wd is not None else d, ws if ws is not None else s, wu if wu is not None else u)


def _scored(rows: Iterable[models.Evidence]) -> list[scoring.ScoredEvidence]:
    out = []
    for r in rows:
        dim_spec = scoring.SIGNALS.get(r.dimension, [])
        out.append(
            scoring.ScoredEvidence(
                dimension=r.dimension,
                signal=r.signal,
                label=scoring.LABELS.get(r.signal, r.signal),
                value=r.value or "",
                points=float(r.points),
                max_points=scoring._max_points(r.dimension, r.signal) if r.signal in dim_spec else 0.0,
                confidence=float(r.confidence),
                source_url=r.source_url,
                snippet=r.snippet,
                extractor=r.extractor,
            )
        )
    return out


def top_evidence(rows: Iterable[models.Evidence], n: int = 3) -> list[str]:
    scored = sorted((e for e in _scored(rows) if e.points > 0), key=lambda e: -e.points)
    return [scoring.chip(e) for e in scored[:n]]


def scores(lead: models.Lead, w: tuple[float, float, float]) -> Scores:
    comp = scoring.composite(lead.durability, lead.succession, lead.upside, *w)
    t, capped = scoring.tier(comp, lead.durability, float(lead.coverage))
    return Scores(
        durability=lead.durability,
        succession=lead.succession,
        upside=lead.upside,
        composite=comp,
        tier=t,
        capped=capped,
    )


def website_url(company: models.Company) -> str | None:
    """Absolute URL for links and exports. CSV rows often hold a bare domain ("acme.com"),
    which a browser would treat as a relative path."""
    raw = (company.raw or {}).get("website") or company.domain
    if not raw:
        return None
    raw = str(raw).strip()
    return raw if raw.lower().startswith(("http://", "https://")) else f"https://{raw}"


def durability_mode(run_mode: str) -> str:
    return "full" if run_mode == "places" else "site_only"


def lead_out(
    lead: models.Lead,
    company: models.Company,
    evidence: Iterable[models.Evidence],
    w: tuple[float, float, float],
    run_mode: str,
) -> LeadOut:
    return LeadOut(
        id=lead.id,
        company_id=company.id,
        name=company.name,
        domain=company.domain,
        website=website_url(company),
        city=company.city,
        region=company.region,
        phone=company.phone_e164,
        founded_year=company.founded_year,
        owner_name=company.owner_name,
        rating=float(company.rating) if company.rating is not None else None,
        review_count=company.review_count,
        scores=scores(lead, w),
        coverage=float(lead.coverage),
        thin_data=scoring.is_thin(float(lead.coverage)),
        top_evidence=top_evidence(evidence),
        email_status=lead.email_status,
        phone_valid=lead.phone_valid,
        crawl_status=company.crawl_status,
        durability_mode=durability_mode(run_mode),
        lat=company.lat,
        lng=company.lng,
    )


def missing_signals(evidence: Iterable[models.Evidence], run_mode: str) -> list[MissingSignal]:
    have = {e.signal for e in evidence}
    out = []
    for dim, sigs in scoring.SIGNALS.items():
        for sig in sigs:
            if sig in have or (run_mode != "places" and sig in scoring.PLACES_ONLY):
                continue
            out.append(
                MissingSignal(
                    dimension=dim,
                    signal=sig,
                    label=scoring.LABELS[sig],
                    max_points=scoring._max_points(dim, sig),
                )
            )
    return out


def lead_detail(
    lead: models.Lead,
    company: models.Company,
    evidence: list[models.Evidence],
    w: tuple[float, float, float],
    run_mode: str,
) -> LeadDetail:
    base = lead_out(lead, company, evidence, w, run_mode)
    order = {sig: i for sigs in scoring.SIGNALS.values() for i, sig in enumerate(sigs)}
    rows = sorted(_scored(evidence), key=lambda e: (e.dimension, order.get(e.signal, 99)))
    raw = company.raw or {}
    return LeadDetail(
        **base.model_dump(),
        evidence=[
            EvidenceOut(
                dimension=e.dimension,
                signal=e.signal,
                label=e.label,
                value=e.value,
                points=e.points,
                max_points=e.max_points,
                confidence=e.confidence,
                source_url=e.source_url,
                snippet=e.snippet,
                extractor=e.extractor,
            )
            for e in rows
        ],
        missing=missing_signals(evidence, run_mode),
        address=company.address or raw.get("street_address_site"),
        postcode=company.postcode,
        email=lead.email,
        owner_title=raw.get("owner_title"),
        owner_source_url=raw.get("owner_source_url"),
        services=raw.get("services") or [],
        tech=raw.get("tech") or [],
        run_id=lead.run_id,
        place_id=company.place_id,
        osm_id=company.osm_id,
    )
