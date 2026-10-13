"""Snapshot a real run as the bundled demo.

    uv run python scripts/export_demo.py <run_id>

Writes:
- data/demo_run.json            DB rows (run, companies, leads, evidence) for POST /api/v1/runs/demo
- api/app/data/demo_run.json    same file, inside the API bundle (Vercel deploys api/ on its own)
- web/public/demo/run.json      API-shaped {run, leads: LeadDetail[]} served from the CDN, so the
                                demo renders instantly with zero keys even if the API is cold
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app import db, demo, models, serialize
from app.config import API_DIR, REPO_DIR
from app.schemas import RunOut

DEMO_RUN_ID = uuid.UUID("0de30000-0000-4000-8000-000000000001")  # stable id: links survive re-exports


async def main(run_id: uuid.UUID) -> None:
    snap = await demo.export(run_id)
    # Give the demo a stable run id, distinct from the source run.
    snap["run"]["id"] = str(DEMO_RUN_ID)
    lead_ids: dict[str, str] = {}
    for lead in snap["leads"]:
        new = str(uuid.uuid5(DEMO_RUN_ID, lead["company_id"]))
        lead_ids[lead["id"]] = new
        lead["id"] = new
        lead["run_id"] = str(DEMO_RUN_ID)
        lead["exported_at"] = None
        lead["hubspot_id"] = None
        lead["feedback"] = None
    body = json.dumps(snap, indent=1, ensure_ascii=False)
    for target in (REPO_DIR / "data" / "demo_run.json", API_DIR / "app" / "data" / "demo_run.json"):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        print("wrote", target, f"{len(body) // 1024} KB")

    # API-shaped static copy for the web app.
    async with db.sessionmaker()() as s:
        run = await s.get(models.Run, run_id)
        assert run is not None
        rows = (
            await s.execute(
                select(models.Lead, models.Company)
                .join(models.Company, models.Company.id == models.Lead.company_id)
                .where(models.Lead.run_id == run_id)
            )
        ).all()
        cids = [c.id for _, c in rows]
        ev = (
            (await s.execute(select(models.Evidence).where(models.Evidence.company_id.in_(cids))))
            .scalars()
            .all()
        )
    by_company: dict[uuid.UUID, list[models.Evidence]] = {}
    for e in ev:
        by_company.setdefault(e.company_id, []).append(e)
    w = serialize.weights(run.preset)
    details = []
    for lead, company in rows:
        d = serialize.lead_detail(lead, company, by_company.get(company.id, []), w, run.mode)
        d.id = uuid.UUID(lead_ids[str(lead.id)])
        d.run_id = DEMO_RUN_ID
        details.append(d.model_dump(mode="json"))
    details.sort(key=lambda d: -d["scores"]["composite"])
    run_out = RunOut.model_validate(run, from_attributes=True).model_dump(mode="json")
    run_out.update({"id": str(DEMO_RUN_ID), "source": "demo"})
    web = REPO_DIR / "web" / "public" / "demo" / "run.json"
    web.parent.mkdir(parents=True, exist_ok=True)
    web.write_text(
        json.dumps({"run": run_out, "leads": details}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print("wrote", web, f"{web.stat().st_size // 1024} KB,", len(details), "leads")
    await db.dispose()


if __name__ == "__main__":
    asyncio.run(main(uuid.UUID(sys.argv[1])))
