"""Postgres-backed rate limits (no Redis): 10 runs/hour/IP and 60 requests/minute/IP.

Counters live in the `cache` table under `rl:` keys and expire with it. If the database is
unreachable the limiter fails open: a rate limit must never take the product down.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import Request
from sqlalchemy import text

from app import db
from app.config import get_settings
from app.problems import Problem

log = logging.getLogger(__name__)

_INCR = text(
    """
    INSERT INTO cache (key, value, expires_at) VALUES (:key, '1'::jsonb, :exp)
    ON CONFLICT (key) DO UPDATE
      SET value = to_jsonb(CASE WHEN cache.expires_at < now() THEN 1 ELSE (cache.value)::int + 1 END),
          expires_at = CASE WHEN cache.expires_at < now() THEN EXCLUDED.expires_at ELSE cache.expires_at END
    RETURNING (value)::int
    """
)


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "unknown"


async def hit(key: str, window: timedelta) -> int:
    try:
        async with db.sessionmaker()() as s:
            n = (await s.execute(_INCR, {"key": key, "exp": datetime.now(UTC) + window})).scalar_one()
            await s.commit()
            return int(n)
    except Exception as e:  # fail open
        log.warning("rate limiter unavailable: %s", e)
        return 0


async def limit_requests(request: Request) -> None:
    """FastAPI dependency: 60 requests/minute/IP."""
    s = get_settings()
    now = datetime.now(UTC)
    key = f"rl:req:{client_ip(request)}:{now:%Y%m%d%H%M}"
    if await hit(key, timedelta(minutes=1)) > s.requests_per_minute_per_ip:
        raise Problem(
            429, "Too many requests", "Limit is 60 requests per minute.", retry_after=60 - now.second
        )


async def limit_runs(request: Request) -> None:
    """10 new runs/hour/IP (thesis + CSV)."""
    s = get_settings()
    now = datetime.now(UTC)
    key = f"rl:{client_ip(request)}:{now:%Y%m%d%H}"
    if await hit(key, timedelta(hours=1)) > s.runs_per_hour_per_ip:
        raise Problem(
            429,
            "Run limit reached",
            f"Limit is {s.runs_per_hour_per_ip} runs per hour. Try the demo run meanwhile.",
            retry_after=3600 - now.minute * 60 - now.second,
        )
