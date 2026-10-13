"""Bundled demo run: export a real run to JSON, and load it back (idempotent, no keys needed).

File format (data/demo_run.json):
  {"version": 1, "run": {...}, "companies": [...], "leads": [...], "evidence": [...]}
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app import db, models
from app.config import APP_DIR, REPO_DIR

CANDIDATES = [REPO_DIR / "data" / "demo_run.json", APP_DIR / "data" / "demo_run.json"]


def demo_path() -> Path:
    for p in CANDIDATES:
        if p.exists():
            return p
    raise FileNotFoundError("data/demo_run.json is not bundled with this deployment")


def _row(obj: Any, cols: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for c in cols:
        v = getattr(obj, c)
        if isinstance(v, uuid.UUID):
            v = str(v)
        elif isinstance(v, datetime):
            v = v.isoformat()
        elif v is not None and type(v).__name__ == "Decimal":
            v = float(v)
        out[c] = v
    return out


def _cols(model: type[models.Base]) -> list[str]:
    return [c.key for c in model.__table__.columns]


async def export(run_id: uuid.UUID) -> dict[str, Any]:
    async with db.sessionmaker()() as s:
        run = await s.get(models.Run, run_id)
        if run is None:
            raise LookupError(run_id)
        leads = (await s.execute(select(models.Lead).where(models.Lead.run_id == run_id))).scalars().all()
        cids = [lead.company_id for lead in leads]
        companies = (
            (await s.execute(select(models.Company).where(models.Company.id.in_(cids)))).scalars().all()
        )
        evidence = (
            (await s.execute(select(models.Evidence).where(models.Evidence.company_id.in_(cids))))
            .scalars()
            .all()
        )
    run_row = _row(run, _cols(models.Run))
    run_row.update({"source": "demo", "lease_until": None})
    return {
        "version": 1,
        "run": run_row,
        "companies": [_row(c, _cols(models.Company)) for c in companies],
        "leads": [_row(lead, _cols(models.Lead)) for lead in leads],
        "evidence": [
            {k: v for k, v in _row(e, _cols(models.Evidence)).items() if k != "id"} for e in evidence
        ],
    }


def _parse_dt(d: dict[str, Any], *keys: str) -> dict[str, Any]:
    for k in keys:
        if d.get(k):
            d[k] = datetime.fromisoformat(d[k])
    return d


async def load(path: Path | None = None) -> uuid.UUID:
    data = json.loads((path or demo_path()).read_text(encoding="utf-8"))
    run_id = uuid.UUID(data["run"]["id"])
    async with db.sessionmaker()() as s:
        if await s.get(models.Run, run_id) is not None:
            return run_id
        for c in data["companies"]:
            c = _parse_dt(dict(c), "crawled_at")
            stmt = insert(models.Company).values(**c).on_conflict_do_nothing()
            await s.execute(stmt)
        await s.flush()
        # Companies may already exist under another id (same domain crawled live); map to the stored row.
        id_map: dict[str, uuid.UUID] = {}
        for c in data["companies"]:
            row = await s.get(models.Company, uuid.UUID(c["id"]))
            if row is None and c.get("domain"):
                row = (
                    await s.execute(select(models.Company).where(models.Company.domain == c["domain"]))
                ).scalar_one_or_none()
            if row is not None:
                id_map[c["id"]] = row.id
        run = _parse_dt(dict(data["run"]), "created_at", "started_at", "finished_at", "lease_until")
        run["plan"] = [str(id_map.get(cid, cid)) for cid in run.get("plan", [])]
        s.add(models.Run(**run))
        await s.flush()
        for lead in data["leads"]:
            lead = _parse_dt(dict(lead), "exported_at", "created_at", "updated_at")
            lead["company_id"] = id_map.get(lead["company_id"], lead["company_id"])
            await s.execute(insert(models.Lead).values(**lead).on_conflict_do_nothing())
        have = {
            (str(e.company_id), e.signal)
            for e in (
                await s.execute(
                    select(models.Evidence).where(models.Evidence.company_id.in_(list(id_map.values())))
                )
            ).scalars()
        }
        for e in data["evidence"]:
            cid = id_map.get(e["company_id"])
            if cid is None or (str(cid), e["signal"]) in have:
                continue
            s.add(models.Evidence(**{**e, "company_id": cid}))
        await s.commit()
    return run_id
