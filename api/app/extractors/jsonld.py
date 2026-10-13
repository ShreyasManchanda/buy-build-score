"""schema.org JSON-LD helpers (pure)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

from app.extractors.base import PageView


def objects(page: PageView) -> Iterator[dict[str, Any]]:
    """Every JSON object found in <script type=application/ld+json>, flattening @graph and lists."""
    for node in page.tree.css('script[type="application/ld+json"]'):
        raw = node.text() or ""
        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        yield from _walk(data)


def _walk(data: Any) -> Iterator[dict[str, Any]]:
    if isinstance(data, list):
        for item in data:
            yield from _walk(item)
    elif isinstance(data, dict):
        yield data
        if "@graph" in data:
            yield from _walk(data["@graph"])
        for key in ("founder", "address", "employee", "member"):
            if isinstance(data.get(key), dict | list):
                yield from _walk(data[key])
