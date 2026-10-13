"""CSV export (SaaSquatch-compatible + scores + evidence) and HubSpot push."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, update

from app import db, models, serialize
from app.config import get_settings
from app.integrations import hubspot
from app.problems import Problem
from app.ratelimit import limit_requests
from app.schemas import Tier

router = APIRouter(tags=["export"], dependencies=[Depends(limit_requests)])

COLUMNS = [
    "Company", "Website", "Phone", "Address", "City", "State", "Founded", "Owner", "Rating", "Reviews",
    "Tier", "Composite", "Durability", "Succession", "Upside", "Coverage", "Email Status",
    "Evidence 1", "Evidence 2", "Evidence 3", "Run ID",
]  # fmt: skip


class WeightsIn(BaseModel):
    durability: float = Field(ge=0, le=100)
    succession: float = Field(ge=0, le=100)
    upside: float = Field(ge=0, le=100)


class ExportIn(BaseModel):
    lead_ids: list[uuid.UUID] | None = Field(default=None, max_length=1000)
    run_id: uuid.UUID | None = None
    tiers: list[Tier] | None = None
    weights: WeightsIn | None = None

    @model_validator(mode="after")
    def _one_source(self) -> ExportIn:
        if not self.lead_ids and not self.run_id:
            raise ValueError("Send lead_ids, or a run_id (optionally with tiers).")
        return self


async def _gather(body: ExportIn) -> list[dict[str, Any]]:
    """Leads + company + evidence, ranked, de-duplicated by company."""
    async with db.sessionmaker()() as s:
        q = (
            select(models.Lead, models.Company, models.Run)
            .join(models.Company, models.Company.id == models.Lead.company_id)
            .join(models.Run, models.Run.id == models.Lead.run_id)
        )
        if body.lead_ids:
            q = q.where(models.Lead.id.in_(body.lead_ids))
        else:
            q = q.where(models.Lead.run_id == body.run_id)
        rows = (await s.execute(q)).all()
        cids = [c.id for _, c, _ in rows]
        ev = (
            (await s.execute(select(models.Evidence).where(models.Evidence.company_id.in_(cids))))
            .scalars()
            .all()
            if cids
            else []
        )
    by_company: dict[uuid.UUID, list[models.Evidence]] = {}
    for e in ev:
        by_company.setdefault(e.company_id, []).append(e)

    out: list[dict[str, Any]] = []
    seen: set[uuid.UUID] = set()
    for lead, company, run in rows:
        if company.id in seen:  # the same business never appears twice in one export
            continue
        seen.add(company.id)
        w = (
            (body.weights.durability, body.weights.succession, body.weights.upside)
            if body.weights
            else serialize.weights(run.preset)
        )
        if sum(w) <= 0:
            raise Problem(422, "Weights must not all be zero")
        sc = serialize.scores(lead, w)
        if body.tiers and sc.tier not in body.tiers:
            continue
        evidence = sorted(
            (e for e in by_company.get(company.id, []) if float(e.points) > 0), key=lambda e: -float(e.points)
        )
        out.append({"lead": lead, "company": company, "run": run, "scores": sc, "evidence": evidence})
    out.sort(key=lambda r: -r["scores"].composite)
    return out


def _evidence_line(e: models.Evidence) -> str:
    from app.pipeline.score import LABELS

    return f"{LABELS.get(e.signal, e.signal)}: {e.value or ''} ({e.source_url or ''})"


def _cell(v: Any) -> str:
    if v is None:
        return ""
    s = str(v)
    # CSV formula injection guard: a cell starting with = + - @ would execute in Excel/Sheets.
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


@router.post("/export/csv", summary="Export leads as CSV (SaaSquatch columns + scores + top 3 evidence)")
async def export_csv(body: ExportIn) -> Response:
    rows = await _gather(body)
    buf = io.StringIO()
    buf.write("﻿")  # UTF-8 BOM so Excel opens it cleanly
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(COLUMNS)
    for r in rows:
        c, lead, sc = r["company"], r["lead"], r["scores"]
        ev = [_evidence_line(e) for e in r["evidence"][:3]]
        ev += [""] * (3 - len(ev))
        w.writerow(
            [
                _cell(x)
                for x in (
                    c.name,
                    c.raw.get("website") or (f"https://{c.domain}" if c.domain else ""),
                    c.phone_e164,
                    c.address or c.raw.get("street_address_site"),
                    c.city,
                    c.region,
                    c.founded_year,
                    c.owner_name,
                    float(c.rating) if c.rating is not None else None,
                    c.review_count,
                    sc.tier,
                    sc.composite,
                    sc.durability,
                    sc.succession,
                    sc.upside,
                    f"{round(float(lead.coverage) * 100)}%",
                    lead.email_status,
                    *ev,
                    str(lead.run_id),
                )
            ]
        )
    if rows:
        async with db.sessionmaker()() as s:
            await s.execute(
                update(models.Lead)
                .where(models.Lead.id.in_([r["lead"].id for r in rows]))
                .values(exported_at=datetime.now(UTC))
            )
            await s.commit()
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    return Response(
        content=buf.getvalue().encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="buy-build-score-{stamp}.csv"'},
    )


class HubspotOut(BaseModel):
    created: int
    updated: int
    failed: list[dict[str, Any]]


@router.post("/export/hubspot", response_model=HubspotOut, summary="Upsert leads into HubSpot Companies (P1)")
async def export_hubspot(body: ExportIn) -> HubspotOut:
    if not get_settings().hubspot_token:
        raise Problem(501, "HubSpot not configured", "Set HUBSPOT_TOKEN on the server to enable this.")
    rows = await _gather(body)
    base = get_settings().public_app_url.rstrip("/")
    push_rows = [
        hubspot.PushRow(
            lead_id=str(r["lead"].id),
            domain=r["company"].domain,
            name=r["company"].name,
            phone=r["company"].phone_e164,
            city=r["company"].city,
            state=r["company"].region,
            founded_year=r["company"].founded_year,
            tier=r["scores"].tier,
            composite=r["scores"].composite,
            durability=r["scores"].durability,
            succession=r["scores"].succession,
            upside=r["scores"].upside,
            evidence=[_evidence_line(e) for e in r["evidence"][:5]],
            run_url=f"{base}/runs/{r['lead'].run_id}?lead={r['lead'].id}",
        )
        for r in rows
    ]
    try:
        result, ids = await hubspot.push(push_rows)
    except hubspot.HubspotNotConfigured as e:
        raise Problem(501, "HubSpot not configured", str(e)) from e
    except Exception as e:
        raise Problem(502, "HubSpot request failed", str(e)[:300], retry_after=30) from e
    if ids:
        async with db.sessionmaker()() as s:
            for lead_id, hid in ids.items():
                await s.execute(
                    update(models.Lead).where(models.Lead.id == uuid.UUID(lead_id)).values(hubspot_id=hid)
                )
            await s.commit()
    return HubspotOut(created=result.created, updated=result.updated, failed=result.failed)
