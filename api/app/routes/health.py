from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app import db
from app.config import get_settings

router = APIRouter(tags=["health"])


class Health(BaseModel):
    ok: bool
    db: bool
    mode: dict[str, bool]


@router.get("/healthz", response_model=Health)
async def healthz() -> Health:
    s = get_settings()
    db_ok = await db.ping()
    return Health(
        ok=db_ok,
        db=db_ok,
        mode={
            "places": s.has_places,
            "llm": s.has_llm,
            "hubspot": bool(s.hubspot_token),
            "pagespeed": bool(s.pagespeed_api_key),
        },
    )
