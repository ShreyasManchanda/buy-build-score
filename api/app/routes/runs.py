from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile, status
from fastapi.responses import StreamingResponse

from app import db, demo, models
from app.config import get_settings
from app.pipeline import dedup
from app.pipeline import run as pipeline
from app.pipeline.csv_import import MAX_BYTES, CsvError, parse_csv
from app.problems import Problem
from app.ratelimit import limit_requests, limit_runs
from app.schemas import CsvRunCreated, Preset, RunCreated, RunOut, ThesisIn

router = APIRouter(tags=["runs"])


def _stream_url(request: Request, run_id: uuid.UUID) -> str:
    return str(request.url_for("stream_run", run_id=run_id).path)


@router.post(
    "/runs",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=RunCreated,
    dependencies=[Depends(limit_runs)],
    summary="Create a run from a thesis (crawling starts when the stream opens)",
)
async def create_run(body: ThesisIn, request: Request) -> RunCreated:
    mode = "places" if get_settings().has_places else "osm"
    async with db.sessionmaker()() as s:
        run = models.Run(
            source="thesis",
            query=body.model_dump(exclude={"preset"}),
            preset=body.preset,
            mode=mode,
            counts={},
        )
        s.add(run)
        await s.commit()
        await s.refresh(run)
    return RunCreated(run_id=run.id, stream_url=_stream_url(request, run.id))


@router.post(
    "/runs/csv",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=CsvRunCreated,
    dependencies=[Depends(limit_runs)],
    summary="Start a run from a SaaSquatch CSV export (multipart `file`)",
)
async def create_csv_run(
    request: Request,
    file: Annotated[UploadFile, File(description="CSV ≤ 2 MB, ≤ 500 rows")],
    preset: Annotated[Preset, Form()] = "searcher",
) -> CsvRunCreated:
    data = await file.read(MAX_BYTES + 1)
    try:
        accepted, rejected, mapping = parse_csv(data)
    except CsvError as e:
        raise Problem(e.status, "CSV rejected", str(e)) from e
    if not accepted:
        raise Problem(422, "No usable rows", "Every row was missing a website or a company name + city.",
                      rejected=rejected[:50])  # fmt: skip
    companies = dedup.dedup(accepted)
    plan = await pipeline.insert_companies(companies)
    async with db.sessionmaker()() as s:
        run = models.Run(
            source="csv",
            query={"filename": file.filename, "rows": len(accepted) + len(rejected), "mapping": mapping},
            preset=preset,
            mode="csv",
            plan=plan,
            counts={"discovered": len(accepted), "deduped": len(companies), "rejected": len(rejected)},
        )
        s.add(run)
        await s.commit()
        await s.refresh(run)
    return CsvRunCreated(
        run_id=run.id,
        stream_url=_stream_url(request, run.id),
        rows_accepted=len(accepted),
        rows_rejected=len(rejected),
        rejected=[{"line": r["line"], "reason": r["reason"]} for r in rejected[:50]],
        mapping=mapping,
    )


@router.post("/runs/demo", response_model=RunCreated, summary="Load the bundled demo run (no keys needed)")
async def create_demo_run(request: Request) -> RunCreated:
    try:
        run_id = await demo.load()
    except FileNotFoundError as e:
        raise Problem(404, "Demo run not bundled", str(e)) from e
    return RunCreated(run_id=run_id, stream_url=_stream_url(request, run_id))


@router.get("/runs/{run_id}", response_model=RunOut, dependencies=[Depends(limit_requests)])
async def get_run(run_id: uuid.UUID) -> RunOut:
    async with db.sessionmaker()() as s:
        run = await s.get(models.Run, run_id)
    if run is None:
        raise Problem(404, "Run not found")
    return RunOut.model_validate(run, from_attributes=True)


@router.get(
    "/runs/{run_id}/stream",
    name="stream_run",
    summary="Runs the pipeline while streaming SSE; replays stored rows if done, resumes if partial",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream_run(run_id: uuid.UUID) -> StreamingResponse:
    return StreamingResponse(
        pipeline.stream(run_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
