from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel
from sqlalchemy import and_, case, func, or_, select

from app import db, models, serialize
from app.pipeline.score import _cfg
from app.problems import Problem
from app.ratelimit import limit_requests
from app.schemas import LeadDetail, LeadPage

router = APIRouter(tags=["leads"], dependencies=[Depends(limit_requests)])

SORTS = {"composite", "durability", "succession", "upside", "name", "founded", "coverage"}


def composite_expr(wd: float, ws: float, wu: float) -> Any:
    total = wd + ws + wu
    raw = (wd * models.Lead.durability + ws * models.Lead.succession + wu * models.Lead.upside) / total
    return func.floor(raw + 0.5)  # half-up, identical to Math.round in the browser


def tier_expr(comp: Any) -> Any:
    cfg = _cfg()
    return case(
        (
            and_(
                comp >= cfg["tiers"]["A"],
                models.Lead.coverage >= cfg["guardrails"]["min_coverage_for_A"],
                models.Lead.durability >= cfg["guardrails"]["durability_floor"],
            ),
            "A",
        ),
        (comp >= cfg["tiers"]["B"], "B"),
        else_="C",
    )


@router.get(
    "/runs/{run_id}/leads", response_model=LeadPage, summary="Ranked leads; composite computed in SQL"
)
async def list_leads(
    run_id: uuid.UUID,
    wd: Annotated[float | None, Query(ge=0, le=100)] = None,
    ws: Annotated[float | None, Query(ge=0, le=100)] = None,
    wu: Annotated[float | None, Query(ge=0, le=100)] = None,
    tier: Annotated[str | None, Query(pattern=r"^[ABC](,[ABC])*$", examples=["A,B"])] = None,
    min_d: Annotated[int, Query(ge=0, le=100)] = 0,
    min_s: Annotated[int, Query(ge=0, le=100)] = 0,
    min_u: Annotated[int, Query(ge=0, le=100)] = 0,
    q: Annotated[str | None, Query(max_length=80)] = None,
    has_owner: bool = False,
    valid_email: bool = False,
    hide_thin: bool = False,
    crawl_status: Annotated[str | None, Query(pattern=r"^[a-z_]+(,[a-z_]+)*$")] = None,
    sort: Annotated[str, Query(pattern=r"^-?[a-z_]+$")] = "-composite",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> LeadPage:
    async with db.sessionmaker()() as s:
        run = await s.get(models.Run, run_id)
        if run is None:
            raise Problem(404, "Run not found")
        w = serialize.weights(run.preset, wd, ws, wu)
        if sum(w) <= 0:
            raise Problem(422, "Weights must not all be zero")
        comp = composite_expr(*w)
        t = tier_expr(comp)

        base = (
            select(models.Lead, models.Company)
            .join(models.Company, models.Company.id == models.Lead.company_id)
            .where(models.Lead.run_id == run_id)
        )
        conds = [
            models.Lead.durability >= min_d,
            models.Lead.succession >= min_s,
            models.Lead.upside >= min_u,
        ]
        if q:
            like = f"%{q.strip()}%"
            conds.append(
                or_(
                    models.Company.name.ilike(like),
                    models.Company.domain.ilike(like),
                    models.Company.city.ilike(like),
                )
            )
        if has_owner:
            conds.append(models.Company.owner_name.is_not(None))
        if valid_email:
            conds.append(models.Lead.email_status == "valid_mx")
        if hide_thin:
            conds.append(models.Lead.coverage >= _cfg()["guardrails"]["min_coverage_for_A"])
        if crawl_status:
            conds.append(models.Company.crawl_status.in_(crawl_status.split(",")))
        base = base.where(*conds)

        # Tier chip counts: the filtered set before the tier filter itself.
        tier_rows = (
            await s.execute(
                select(t, func.count())
                .select_from(models.Lead)
                .join(models.Company, models.Company.id == models.Lead.company_id)
                .where(models.Lead.run_id == run_id, *conds)
                .group_by(t)
            )
        ).all()
        tier_counts = {"A": 0, "B": 0, "C": 0} | {str(k): int(v) for k, v in tier_rows}

        if tier:
            base = base.where(t.in_(tier.split(",")))
        total = (await s.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

        desc = sort.startswith("-")
        key = sort.lstrip("-")
        if key not in SORTS:
            raise Problem(422, "Unknown sort", f"sort must be one of {sorted(SORTS)}")
        col = {
            "composite": comp,
            "durability": models.Lead.durability,
            "succession": models.Lead.succession,
            "upside": models.Lead.upside,
            "name": func.lower(models.Company.name),
            "founded": models.Company.founded_year,
            "coverage": models.Lead.coverage,
        }[key]
        order = col.desc().nulls_last() if desc else col.asc().nulls_last()
        rows = (
            await s.execute(
                base.order_by(order, func.lower(models.Company.name))
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        ids = [c.id for _, c in rows]
        evidence = (
            (await s.execute(select(models.Evidence).where(models.Evidence.company_id.in_(ids))))
            .scalars()
            .all()
            if ids
            else []
        )
    by_company: dict[uuid.UUID, list[models.Evidence]] = {}
    for e in evidence:
        by_company.setdefault(e.company_id, []).append(e)
    items = [serialize.lead_out(lead, c, by_company.get(c.id, []), w, run.mode) for lead, c in rows]
    return LeadPage(items=items, total=int(total), tier_counts=tier_counts)


@router.get("/leads/{lead_id}", response_model=LeadDetail, summary="One lead with full evidence")
async def get_lead(
    lead_id: uuid.UUID,
    wd: Annotated[float | None, Query(ge=0, le=100)] = None,
    ws: Annotated[float | None, Query(ge=0, le=100)] = None,
    wu: Annotated[float | None, Query(ge=0, le=100)] = None,
) -> LeadDetail:
    async with db.sessionmaker()() as s:
        lead = await s.get(models.Lead, lead_id)
        if lead is None:
            raise Problem(404, "Lead not found")
        company = await s.get(models.Company, lead.company_id)
        run = await s.get(models.Run, lead.run_id)
        evidence = list(
            (await s.execute(select(models.Evidence).where(models.Evidence.company_id == lead.company_id)))
            .scalars()
            .all()
        )
    assert company is not None and run is not None
    w = serialize.weights(run.preset, wd, ws, wu)
    return serialize.lead_detail(lead, company, evidence, w, run.mode)


class FeedbackIn(BaseModel):
    vote: Literal[1, -1]


@router.post("/leads/{lead_id}/feedback", status_code=204, summary="Thumbs up/down on a lead's tier (P2)")
async def feedback(lead_id: uuid.UUID, body: FeedbackIn) -> Response:
    async with db.sessionmaker()() as s:
        lead = await s.get(models.Lead, lead_id)
        if lead is None:
            raise Problem(404, "Lead not found")
        lead.feedback = body.vote
        await s.commit()
    return Response(status_code=204)
