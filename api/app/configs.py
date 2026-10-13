"""Loads the YAML config files once. They are data, edited without code changes."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from app.config import APP_DIR


def _load(name: str) -> dict[str, Any]:
    with open(APP_DIR / name, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert isinstance(data, dict), f"{name} must be a mapping"
    return data


@lru_cache
def scoring() -> dict[str, Any]:
    return _load("scoring.yaml")


@lru_cache
def fingerprints() -> dict[str, Any]:
    return _load("fingerprints.yaml")


@lru_cache
def osm_tags() -> dict[str, Any]:
    return _load("osm_tags.yaml")


@lru_cache
def extract_prompt() -> str:
    return (APP_DIR / "prompts" / "extract.md").read_text(encoding="utf-8")
