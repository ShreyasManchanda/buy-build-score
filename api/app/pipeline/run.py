"""The run. `GET /runs/{id}/stream` iterates `stream()`, which *is* the pipeline:

discover -> dedup -> per company (crawl -> extract -> score -> save -> emit `lead`), concurrently,
streaming each row as it finishes. No background task outlives the response:

- at RUN_TIME_BUDGET_SECONDS (280 s) it stops, cancels unfinished companies and emits `resume`;
- reopening a partial run resumes with only unscored companies (crawls are cached for 7 days);
- reopening a finished run replays stored leads;
- a second stream of a run that's already executing follows it (polls) instead of running twice.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert

from app import db, models, serialize
from app.config import get_settings
from app.integrations import osm as osm_api
from app.integrations import pagespeed
from app.integrations import places as places_api
from app.integrations.llm import LlmBatcher
from app.pipeline import dedup as dedup_mod
from app.pipeline import discover as discover_mod
from app.pipeline import geocode as geocode_mod
from app.pipeline import validate
from app.pipeline.crawl import Crawler, CrawlResult
from app.pipeline.extract import extract, raw_facts
from app.pipeline.score import CompanyFacts, score
from app.schemas import CompanyIn, LeadOut

log = logging.getLogger(__name__)

HEARTBEAT_S = 15.0
LEASE_S = 45
FOLLOW_POLL_S = 2.0


def sse(event: str, data: Any) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str, separators=(',', ':'))}\n\n"


HEARTBEAT = ": keep-alive\n\n"


@dataclass
class Ctx:
    run_id: uuid.UUID
    preset: str
    mode: str
    deadline: float
    started: float
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)

    def bump(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n

    def status(self, status: str) -> str:
        return sse("status", {"status": status, "counts": self.counts, "mode": self.mode})


# ---------------------------------------------------------------- db helpers


async def _update_run(run_id: uuid.UUID, **values: Any) -> None:
    async with db.sessionmaker()() as s:
        await s.execute(update(models.Run).where(models.Run.id == run_id).values(**values))
        await s.commit()


async def acquire_lease(run_id: uuid.UUID) -> bool:
    async with db.sessionmaker()() as s:
        row = (
            await s.execute(
                text(
                    "UPDATE runs SET lease_until = now() + make_interval(secs => :secs) "
                    "WHERE id = :id AND (lease_until IS NULL OR lease_until < now()) RETURNING id"
                ),
                {"id": run_id, "secs": LEASE_S},
            )
        ).first()
        await s.commit()
        return row is not None


async def renew_lease(run_id: uuid.UUID) -> None:
    async with db.sessionmaker()() as s:
        await s.execute(
            text("UPDATE runs SET lease_until = now() + make_interval(secs => :secs) WHERE id = :id"),
            {"id": run_id, "secs": LEASE_S},
        )
        await s.commit()


async def release_lease(run_id: uuid.UUID) -> None:
    try:
        await _update_run(run_id, lease_until=None)
    except Exception as e:  # pragma: no cover
        log.warning("lease release failed: %s", e)


def _company_raw(c: CompanyIn) -> dict[str, Any]:
    raw = dict(c.raw)
    raw.update(
        {
            "website": c.website,
            "discovered_email": c.email,
            "business_status": c.business_status,
            "newest_review_at": c.newest_review_at.isoformat() if c.newest_review_at else None,
            "osm_start_year": int(c.start_date) if c.start_date and c.start_date.isdigit() else None,
            "source": c.source,
            "merged_from": c.merged_from,
        }
    )
    return {k: v for k, v in raw.items() if v not in (None, "", [])}


async def upsert_company(c: CompanyIn) -> uuid.UUID:
    """Companies are global (keyed by domain / OSM id / Place id) so runs share crawls and evidence."""
    async with db.sessionmaker()() as s:
        existing: models.Company | None = None
        for col, val in (
            (models.Company.domain, c.domain),
            (models.Company.osm_id, c.osm_id),
            (models.Company.place_id, c.place_id),
        ):
            if val:
                existing = (await s.execute(select(models.Company).where(col == val))).scalar_one_or_none()
                if existing:
                    break
        if existing is None and not c.domain and c.postcode:
            existing = (
                await s.execute(
                    select(models.Company).where(
                        models.Company.name == c.name, models.Company.postcode == c.postcode
                    )
                )
            ).scalar_one_or_none()
        fields = {
            "name": c.name,
            "domain": c.domain,
            "phone_e164": c.phone_e164,
            "address": c.address,
            "city": c.city,
            "region": c.region,
            "postcode": c.postcode,
            "country": c.country,
            "lat": c.lat,
            "lng": c.lng,
            "place_id": c.place_id,
            "osm_id": c.osm_id,
            "rating": c.rating,
            "review_count": c.review_count,
        }
        if existing is None:
            company = models.Company(
                **{k: v for k, v in fields.items() if v is not None}, raw=_company_raw(c)
            )
            if not c.website:
                company.crawl_status = "no_site"
            s.add(company)
        else:
            company = existing
            for k, v in fields.items():
                if v is not None:
                    setattr(company, k, v)
            company.raw = {**(company.raw or {}), **_company_raw(c)}
        await s.commit()
        return company.id


async def insert_companies(companies: list[CompanyIn]) -> list[str]:
    ids: list[str] = []
    for c in companies:
        cid = str(await upsert_company(c))
        if cid not in ids:
            ids.append(cid)
    return ids


async def _load_leads(run_id: uuid.UUID) -> list[tuple[models.Lead, models.Company, list[models.Evidence]]]:
    async with db.sessionmaker()() as s:
        rows = (
            await s.execute(
                select(models.Lead, models.Company)
                .join(models.Company, models.Company.id == models.Lead.company_id)
                .where(models.Lead.run_id == run_id)
            )
        ).all()
        ids = [c.id for _, c in rows]
        ev_rows = (
            (await s.execute(select(models.Evidence).where(models.Evidence.company_id.in_(ids))))
            .scalars()
            .all()
            if ids
            else []
        )
    by_company: dict[uuid.UUID, list[models.Evidence]] = {}
    for e in ev_rows:
        by_company.setdefault(e.company_id, []).append(e)
    return [(lead, comp, by_company.get(comp.id, [])) for lead, comp in rows]


async def save_result(
    ctx: Ctx,
    company_id: uuid.UUID,
    crawl: CrawlResult,
    raw_extra: dict[str, Any],
    result: Any,
    email: str | None,
    email_status: str | None,
    phone_valid: bool | None,
) -> tuple[models.Lead, models.Company, list[models.Evidence]]:
    now = datetime.now(UTC)
    async with db.sessionmaker()() as s:
        company = await s.get(models.Company, company_id)
        assert company is not None
        company.crawl_status = crawl.status
        if crawl.status != "no_site":
            company.crawled_at = now
        company.founded_year = result.founded_year
        company.owner_name = result.owner_name
        company.raw = {
            **(company.raw or {}),
            **raw_extra,
            "crawl": {
                "status": crawl.status,
                "error": crawl.error,
                "final_scheme": crawl.final_scheme,
                "tls_ok": crawl.tls_ok,
                "ttfb_ms": crawl.ttfb_ms,
                "pages": [{"kind": p.kind, "url": p.final_url} for p in crawl.pages],
                "skipped_by_robots": crawl.skipped_by_robots,
                "js_rendered": crawl.js_rendered,
                "cached": crawl.cached,
            },
        }
        await s.execute(delete(models.Evidence).where(models.Evidence.company_id == company_id))
        evidence = [
            models.Evidence(
                company_id=company_id,
                dimension=e.dimension,
                signal=e.signal,
                value=e.value[:500] if e.value else None,
                points=e.points,
                confidence=e.confidence,
                source_url=e.source_url,
                snippet=(e.snippet or None) and e.snippet[:200],
                extractor=e.extractor,
            )
            for e in result.evidence
        ]
        s.add_all(evidence)
        values = {
            "run_id": ctx.run_id,
            "company_id": company_id,
            "durability": result.durability,
            "succession": result.succession,
            "upside": result.upside,
            "coverage": result.coverage,
            "email": email,
            "email_status": email_status,
            "phone_valid": phone_valid,
            "updated_at": now,
        }
        stmt = insert(models.Lead).values(**values)
        stmt = stmt.on_conflict_do_update(
            constraint="leads_run_company_key",
            set_={k: v for k, v in values.items() if k not in ("run_id", "company_id")},
        )
        await s.execute(stmt)
        await s.commit()
        lead = (
            await s.execute(
                select(models.Lead).where(
                    models.Lead.run_id == ctx.run_id, models.Lead.company_id == company_id
                )
            )
        ).scalar_one()
        await s.refresh(company)
        return lead, company, evidence


# ---------------------------------------------------------------- per company


async def process_company(
    ctx: Ctx, company_id: uuid.UUID, crawler: Crawler, batcher: LlmBatcher
) -> tuple[LeadOut, dict[str, Any] | None]:
    async with db.sessionmaker()() as s:
        company = await s.get(models.Company, company_id)
        assert company is not None
        name, raw = company.name, dict(company.raw or {})
        website = raw.get("website") or (f"http://{company.domain}" if company.domain else None)
        phone = company.phone_e164
        # A street address counts only when discovery actually gave one (OSM street tags, Places, CSV).
        has_street = raw.get("osm_street") or raw.get("has_street") or raw.get("source") == "csv"
        newest = raw.get("newest_review_at")
        facts = CompanyFacts(
            name=name,
            mode=ctx.mode,
            osm_id=company.osm_id,
            osm_start_year=raw.get("osm_start_year"),
            place_id=company.place_id,
            rating=float(company.rating) if company.rating is not None else None,
            review_count=company.review_count,
            business_status=raw.get("business_status"),
            newest_review_at=datetime.fromisoformat(newest) if newest else None,
            street_address=company.address if company.address and has_street else None,
        )

    # PageSpeed (only with a key) runs alongside the crawl; it never delays a lead on its own.
    crawl, psi = await asyncio.gather(crawler.crawl(website), pagespeed.mobile_score(website))
    if crawl.pages:
        ctx.bump("crawled")
    ctx.bump(crawl.status)

    ex = await extract(crawl, str(company_id), name, batcher, datetime.now(UTC).year)
    facts.website_responds = crawl.reachable
    facts.home_url = crawl.home.final_url if crawl.home else website
    facts.pagespeed = psi if crawl.reachable else None
    result = score(ex.facts, facts, crawl.status)

    email = ex.facts["email"].value if "email" in ex.facts else raw.get("discovered_email")
    email_status = await validate.email_status(email)
    phone_valid = validate.phone_valid(phone)
    lead, company_row, evidence = await save_result(
        ctx, company_id, crawl, raw_facts(ex), result, email, email_status, phone_valid
    )
    ctx.bump("scored")
    w = serialize.weights(ctx.preset)
    out = serialize.lead_out(lead, company_row, evidence, w, ctx.mode)

    warning = None
    if crawl.status in ("blocked_robots", "unreachable"):
        reason = {
            "blocked_robots": "robots.txt disallows crawling — scored from discovery data only",
            "unreachable": f"website unreachable ({crawl.error or 'no response'})",
        }[crawl.status]
        warning = {"company": name, "lead_id": str(lead.id), "reason": reason}
    return out, warning


# ---------------------------------------------------------------- discovery


async def run_discovery(ctx: Ctx, run: models.Run) -> AsyncIterator[str]:
    q = run.query
    yield ctx.status("discovering")
    await _update_run(ctx.run_id, status="discovering", started_at=datetime.now(UTC))

    async def _find() -> tuple[Any, discover_mod.Discovery]:
        g = await geocode_mod.geocode(q["location"])
        f = await discover_mod.discover(
            q["industry"], q["location"], g, int(q["radius_km"]), int(q["max_results"]), bool(q.get("expand"))
        )
        return g, f

    # Discovery can take up to a minute on busy Overpass servers; keep the stream alive meanwhile.
    task = asyncio.create_task(_find())
    try:
        while not task.done():
            await asyncio.wait({task}, timeout=HEARTBEAT_S)
            if not task.done():
                yield HEARTBEAT
    finally:
        if not task.done():
            task.cancel()
    geo, found = task.result()
    ctx.mode = found.mode
    for w in found.warnings:
        warn = {"company": None, "reason": w, "upstream": True}
        ctx.warnings.append(warn)
        yield sse("warning", warn)
    deduped = dedup_mod.dedup(found.companies, default_region=geo.country_code or "US")
    ctx.counts.update(
        {"discovered": len(found.companies), "deduped": len(deduped), "chains_dropped": found.chains_dropped}
    )
    plan = await insert_companies(deduped)
    await _update_run(
        ctx.run_id,
        plan=plan,
        mode=ctx.mode,
        counts=ctx.counts,
        warnings=ctx.warnings,
        query={**q, "geo": {"lat": geo.lat, "lng": geo.lng, "display_name": geo.display_name}},
    )
    run.plan = plan


# ---------------------------------------------------------------- stream


async def replay(ctx: Ctx) -> AsyncIterator[str]:
    w = serialize.weights(ctx.preset)
    rows = await _load_leads(ctx.run_id)
    outs = [serialize.lead_out(lead, comp, ev, w, ctx.mode) for lead, comp, ev in rows]
    outs.sort(key=lambda o: -o.scores.composite)
    for o in outs:
        yield sse("lead", o.model_dump(mode="json"))


async def follow(ctx: Ctx) -> AsyncIterator[str]:
    """Another stream holds the lease: mirror its progress from the DB instead of running twice."""
    seen: dict[str, datetime] = {}
    last_beat = time.monotonic()
    while time.monotonic() < ctx.deadline:
        async with db.sessionmaker()() as s:
            run = await s.get(models.Run, ctx.run_id)
        assert run is not None
        rows = await _load_leads(ctx.run_id)
        w = serialize.weights(ctx.preset)
        for lead, comp, ev in rows:
            if seen.get(str(lead.id)) != lead.updated_at:
                seen[str(lead.id)] = lead.updated_at
                yield sse("lead", serialize.lead_out(lead, comp, ev, w, run.mode).model_dump(mode="json"))
                last_beat = time.monotonic()
        if run.status in ("done", "failed"):
            yield sse(
                "done" if run.status == "done" else "error", {"counts": run.counts, "message": run.error}
            )
            return
        if run.lease_until is None or run.lease_until < datetime.now(UTC):
            yield sse("resume", {"remaining": max(0, len(run.plan) - len(rows)), "reason": "runner stopped"})
            return
        if time.monotonic() - last_beat > HEARTBEAT_S:
            yield HEARTBEAT
            last_beat = time.monotonic()
        await asyncio.sleep(FOLLOW_POLL_S)
    yield sse("resume", {"remaining": None, "reason": "time budget"})


async def stream(run_id: uuid.UUID) -> AsyncIterator[str]:
    settings = get_settings()
    started = time.monotonic()
    async with db.sessionmaker()() as s:
        run = await s.get(models.Run, run_id)
    if run is None:
        yield sse("error", {"message": "Run not found"})
        return
    ctx = Ctx(
        run_id=run.id,
        preset=run.preset,
        mode=run.mode,
        deadline=started + settings.run_time_budget_seconds,
        started=started,
        counts=dict(run.counts or {}),
        warnings=list(run.warnings or []),
    )

    if run.status in ("done", "failed"):
        yield ctx.status(run.status)
        for w in ctx.warnings:
            yield sse("warning", w)
        async for ev in replay(ctx):
            yield ev
        if run.status == "done":
            yield sse("done", {"counts": ctx.counts, "duration_ms": _duration_ms(run), "replayed": True})
        else:
            yield sse("error", {"message": run.error or "Run failed"})
        return

    if not await acquire_lease(run.id):
        yield ctx.status(run.status)
        async for ev in follow(ctx):
            yield ev
        return

    try:
        async for ev in _execute(ctx, run):
            yield ev
    except geocode_mod.GeocodeError as e:
        # Permanent: the location doesn't exist. The run is over.
        await _update_run(
            run.id, status="failed", error=str(e), finished_at=datetime.now(UTC), counts=ctx.counts
        )
        yield sse("error", {"message": str(e)})
    except (osm_api.OverpassError, places_api.PlacesError) as e:
        # Transient (public servers busy): keep the run resumable; reopening retries discovery.
        await _update_run(run.id, error=str(e), counts=ctx.counts)
        yield sse("error", {"message": f"{e} Reload this page to retry.", "retryable": True})
    except Exception as e:
        log.exception("run %s failed", run.id)
        # Leave the status alone: scored leads are kept and reopening resumes the rest.
        await _update_run(run.id, error=f"{type(e).__name__}: {e}", counts=ctx.counts)
        yield sse(
            "error",
            {
                "message": "Something went wrong while running this thesis. Reload to resume.",
                "retryable": True,
            },
        )
    finally:
        await release_lease(run.id)


async def _execute(ctx: Ctx, run: models.Run) -> AsyncIterator[str]:
    if not run.plan:
        if run.source != "thesis":
            raise RuntimeError("run has no companies")
        async for ev in run_discovery(ctx, run):
            yield ev
        if not run.plan:
            await _update_run(ctx.run_id, status="done", finished_at=datetime.now(UTC), counts=ctx.counts)
            yield ctx.status("done")
            yield sse("done", {"counts": ctx.counts, "duration_ms": _elapsed_ms(ctx), "empty": True})
            return

    # Resume: leads already scored are replayed, the rest are processed.
    async for ev in replay(ctx):
        yield ev
    async with db.sessionmaker()() as s:
        scored = {
            str(x)
            for x in (await s.execute(select(models.Lead.company_id).where(models.Lead.run_id == ctx.run_id)))
            .scalars()
            .all()
        }
    remaining = [uuid.UUID(c) for c in run.plan if c not in scored]
    ctx.counts["scored"] = len(scored)
    ctx.counts.setdefault("deduped", len(run.plan))

    await _update_run(
        ctx.run_id, status="crawling", counts=ctx.counts, started_at=run.started_at or datetime.now(UTC)
    )
    yield ctx.status("crawling")

    async with Crawler() as crawler:
        batcher = LlmBatcher()
        tasks = {asyncio.create_task(process_company(ctx, cid, crawler, batcher)): cid for cid in remaining}
        pending = set(tasks)
        last_status = time.monotonic()
        last_lease = time.monotonic()
        try:
            while pending:
                budget = ctx.deadline - time.monotonic()
                if budget <= 0:
                    break
                done, pending = await asyncio.wait(
                    pending, timeout=min(HEARTBEAT_S, budget), return_when=asyncio.FIRST_COMPLETED
                )
                if not done:
                    yield HEARTBEAT
                for t in done:
                    exc = t.exception()
                    if exc is not None:
                        ctx.bump("failed")
                        log.warning("company %s failed: %r", tasks[t], exc)
                        yield sse("warning", {"company": str(tasks[t]), "reason": "processing error"})
                        continue
                    lead, warning = t.result()
                    yield sse("lead", lead.model_dump(mode="json"))
                    if warning:
                        yield sse("warning", warning)
                now = time.monotonic()
                if now - last_status > 1.0 or not pending:
                    last_status = now
                    yield ctx.status("crawling" if pending else "scoring")
                if now - last_lease > 15:
                    last_lease = now
                    await renew_lease(ctx.run_id)
                    await _update_run(ctx.run_id, counts=ctx.counts)
        finally:
            for t in pending:
                t.cancel()
            await batcher.drain()
        ctx.counts["llm_calls"] = ctx.counts.get("llm_calls", 0) + batcher.calls

    if pending:
        remaining_n = len(pending)
        await _update_run(ctx.run_id, status="crawling", counts=ctx.counts)
        yield sse(
            "resume", {"remaining": remaining_n, "reason": "time budget", "elapsed_ms": _elapsed_ms(ctx)}
        )
        return

    await _update_run(ctx.run_id, status="done", finished_at=datetime.now(UTC), counts=ctx.counts)
    yield ctx.status("done")
    yield sse("done", {"counts": ctx.counts, "duration_ms": _elapsed_ms(ctx)})


def _elapsed_ms(ctx: Ctx) -> int:
    return int((time.monotonic() - ctx.started) * 1000)


def _duration_ms(run: models.Run) -> int | None:
    if run.started_at and run.finished_at:
        return int((run.finished_at - run.started_at).total_seconds() * 1000)
    return None
