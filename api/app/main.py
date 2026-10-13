"""Buy & Build Score API. Every route lives under /api/v1; OpenAPI at /api/v1/docs."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db, problems
from app.config import get_settings
from app.routes import health

PREFIX = "/api/v1"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await db.dispose()


app = FastAPI(
    title="Buy & Build Score API",
    version="0.1.0",
    summary="Ranks owner-operated small businesses as acquisition targets with evidence-backed scores.",
    docs_url=f"{PREFIX}/docs",
    redoc_url=f"{PREFIX}/redoc",
    openapi_url=f"{PREFIX}/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
problems.install(app)

api = APIRouter(prefix=PREFIX)
api.include_router(health.router)
app.include_router(api)
