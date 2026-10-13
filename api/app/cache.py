"""Two-level read-through cache: per-instance TTLCache, then the Postgres `cache` table.

Postgres errors never break a run: the cache degrades to memory-only and logs once.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from cachetools import TTLCache
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app import db
from app.models import Cache

log = logging.getLogger(__name__)

HOUR = 3600
DAY = 24 * HOUR

TTL = {
    "osm": DAY,
    "places": DAY,
    "crawl": 7 * DAY,
    "robots": DAY,
    "mx": 7 * DAY,
    "llm": 30 * DAY,
    "geo": 30 * DAY,
}

_mem: TTLCache[str, tuple[datetime, Any]] = TTLCache(maxsize=4096, ttl=7 * DAY)
_db_enabled = True


def sha1(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def key_for(prefix: str, *parts: object) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str)
    return f"{prefix}:{sha1(raw)}"


def disable_db() -> None:
    """Used by unit tests that run without Postgres."""
    global _db_enabled
    _db_enabled = False


def enable_db() -> None:
    global _db_enabled
    _db_enabled = True


def clear_memory() -> None:
    _mem.clear()


async def get(key: str) -> Any | None:
    now = datetime.now(UTC)
    hit = _mem.get(key)
    if hit is not None:
        expires_at, value = hit
        if expires_at > now:
            return value
        _mem.pop(key, None)
    if not _db_enabled:
        return None
    try:
        async with db.sessionmaker()() as s:
            row = (await s.execute(select(Cache).where(Cache.key == key))).scalar_one_or_none()
            if row is None or row.expires_at <= now:
                return None
            _mem[key] = (row.expires_at, row.value)
            return row.value
    except Exception as e:  # pragma: no cover - network/db failure path
        log.warning("cache get failed for %s: %s", key, e)
        return None


async def set(key: str, value: Any, ttl_seconds: int) -> None:
    expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    _mem[key] = (expires_at, value)
    if not _db_enabled:
        return
    try:
        async with db.sessionmaker()() as s:
            stmt = insert(Cache).values(key=key, value=value, expires_at=expires_at)
            stmt = stmt.on_conflict_do_update(
                index_elements=[Cache.key], set_={"value": value, "expires_at": expires_at}
            )
            await s.execute(stmt)
            await s.commit()
    except Exception as e:  # pragma: no cover
        log.warning("cache set failed for %s: %s", key, e)


async def get_or_set[T](key: str, ttl_seconds: int, factory: Callable[[], Awaitable[T]]) -> T:
    hit = await get(key)
    if hit is not None:
        return hit
    value = await factory()
    if value is not None:
        await set(key, value, ttl_seconds)
    return value


async def purge_expired() -> int:
    if not _db_enabled:
        return 0
    async with db.sessionmaker()() as s:
        res = await s.execute(delete(Cache).where(Cache.expires_at < datetime.now(UTC)))
        await s.commit()
        return int(getattr(res, "rowcount", 0) or 0)
