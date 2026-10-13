"""tech_fingerprints (booking/chat/analytics/cms/legacy from fingerprints.yaml) + table_layout."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from app import configs
from app.extractors.base import Evidence, Pages

CATEGORIES = ("booking", "chat", "analytics", "cms", "legacy")


@lru_cache
def _compiled() -> dict[str, list[tuple[str, re.Pattern[str], re.Pattern[str] | None]]]:
    out: dict[str, list[tuple[str, re.Pattern[str], re.Pattern[str] | None]]] = {}
    for cat, entries in configs.fingerprints().items():
        out[cat] = [
            (
                e["name"],
                re.compile(e["pattern"], re.I),
                re.compile(e["version"], re.I) if e.get("version") else None,
            )
            for e in entries
        ]
    return out


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def tech_fingerprints(pages: Pages) -> list[Evidence]:
    """One Evidence per category (value = list of detected tool names), always emitted when pages exist."""
    if not pages.pages:
        return []
    out: list[Evidence] = []
    for cat, entries in _compiled().items():
        hits: list[dict[str, Any]] = []
        for name, pat, ver in entries:
            for p in pages.pages:
                m = pat.search(p.html)
                if not m:
                    continue
                hit: dict[str, Any] = {"name": name, "url": p.url, "match": m.group(0)[:80]}
                if ver:
                    vm = ver.search(p.html)
                    if vm:
                        hit["version"] = vm.group(1)
                hits.append(hit)
                break
        # WordPress counts as "legacy" only when its generator version is < 6.0.
        if cat == "cms":
            for h in hits:
                if h["name"] == "WordPress" and h.get("version") and _version_tuple(h["version"]) < (6, 0):
                    h["outdated"] = True
        names = [h["name"] + (f" {h['version']}" if h.get("version") else "") for h in hits]
        first = hits[0] if hits else None
        out.append(
            Evidence(
                f"tech_{cat}",
                [h["name"] for h in hits],
                ", ".join(names) if names else "none",
                first["url"] if first else pages.home_url,
                snippet=(
                    f"Found {first['match']!r}"
                    if first
                    else f"No {cat} scripts on {len(pages.pages)} page(s)"
                )[:200],
                extra={"hits": hits},
            )
        )
    return out


def table_layout(pages: Pages) -> list[Evidence]:
    home = pages.home
    if home is None:
        return []
    tables = len(home.tree.css("table"))
    semantic = bool(home.tree.css_first("main, section, article"))
    is_table_layout = tables > 5 and not semantic
    return [
        Evidence(
            "table_layout",
            is_table_layout,
            f"{tables} <table> tags" + ("" if semantic else ", no <main>/<section>"),
            home.url,
            snippet=f"{tables} tables, semantic layout tags {'present' if semantic else 'absent'}",
        )
    ]
