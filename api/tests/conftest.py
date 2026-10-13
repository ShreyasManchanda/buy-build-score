from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from sqlalchemy import text

from app import cache, db
from app.config import API_DIR, get_settings

FIXTURES = Path(__file__).parent / "fixtures"


def _test_db_url() -> str:
    return os.environ.get("TEST_DATABASE_URL") or get_settings().test_database_url


@pytest.fixture(autouse=True)
def _memory_cache(request: pytest.FixtureRequest) -> Iterator[None]:
    """Unit tests never touch Postgres through the cache unless marked `db`."""
    from app.integrations import llm

    cache.clear_memory()
    llm._down_until.clear()
    if request.node.get_closest_marker("db") is None:
        cache.disable_db()
    yield
    cache.enable_db()
    cache.clear_memory()
    llm._down_until.clear()


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if _test_db_url():
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set (needs a real Postgres)")
    for item in items:
        if item.get_closest_marker("db"):
            item.add_marker(skip)


_migrated: set[str] = set()


def _migrate() -> None:
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture
async def pg(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """A clean, migrated test database; every optional key switched off (no real LLM/Places calls)."""
    url = _test_db_url()
    monkeypatch.setenv("DATABASE_URL", url)
    for key in (
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "GOOGLE_PLACES_API_KEY",
        "HUBSPOT_TOKEN",
        "PAGESPEED_API_KEY",
    ):
        monkeypatch.setenv(key, "")
    get_settings.cache_clear()
    await db.dispose()
    if url not in _migrated:
        await asyncio.to_thread(_migrate)
        _migrated.add(url)
    async with db.get_engine().begin() as conn:
        await conn.execute(text("TRUNCATE evidence, leads, runs, companies, cache CASCADE"))
    yield
    await db.dispose()
    get_settings.cache_clear()
