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
    """Idempotent and safe under concurrent calls (two Export clicks): every insert is
    ON CONFLICT DO NOTHING, in bulk, so a second loader is a no-op instead of a 500."""
    data = json.loads((path or demo_path()).read_text(encoding="utf-8"))
    run_id = uuid.UUID(data["run"]["id"])
    async with db.sessionmaker()() as s:
        if await s.get(models.Run, run_id) is not None:
            return run_id
        companies = [_parse_dt(dict(c), "crawled_at") for c in data["companies"]]
        if companies:
            await s.execute(insert(models.Company).values(companies).on_conflict_do_nothing())
        # Companies may already exist under another id (same domain crawled live); map to the stored row.
        ids = [uuid.UUID(c["id"]) for c in data["companies"]]
        domains = [c["domain"] for c in data["companies"] if c.get("domain")]
        stored = (
            await s.execute(
                select(models.Company.id, models.Company.domain).where(
                    (models.Company.id.in_(ids)) | (models.Company.domain.in_(domains))
                )
            )
        ).all()
        by_id = {str(i) for i, _ in stored}
        by_domain = {d: i for i, d in stored if d}
        id_map: dict[str, uuid.UUID] = {}
        for c in data["companies"]:
            if c["id"] in by_id:
                id_map[c["id"]] = uuid.UUID(c["id"])
            elif c.get("domain") in by_domain:
                id_map[c["id"]] = by_domain[c["domain"]]

        run = _parse_dt(dict(data["run"]), "created_at", "started_at", "finished_at", "lease_until")
        run["plan"] = [str(id_map.get(cid, cid)) for cid in run.get("plan", [])]
        await s.execute(insert(models.Run).values(**run).on_conflict_do_nothing())
        leads = []
        for lead in data["leads"]:
            lead = _parse_dt(dict(lead), "exported_at", "created_at", "updated_at")
            if lead["company_id"] in id_map:
                lead["company_id"] = id_map[lead["company_id"]]
                leads.append(lead)
        if leads:
            await s.execute(insert(models.Lead).values(leads).on_conflict_do_nothing())
        evidence = [
            {**e, "company_id": id_map[e["company_id"]]}
            for e in data["evidence"]
            if e["company_id"] in id_map
        ]
        if evidence:
            await s.execute(insert(models.Evidence).values(evidence).on_conflict_do_nothing())
        await s.commit()
    return run_id
