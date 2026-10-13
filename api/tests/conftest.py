from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from app import cache

FIXTURES = Path(__file__).parent / "fixtures"


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
    if os.environ.get("TEST_DATABASE_URL"):
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set (needs a real Postgres)")
    for item in items:
        if item.get_closest_marker("db"):
            item.add_marker(skip)
