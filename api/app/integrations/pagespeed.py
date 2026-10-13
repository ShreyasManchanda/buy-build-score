"""PageSpeed Insights mobile performance score (P1, only with PAGESPEED_API_KEY; free 25k/day).

Runs concurrently with the crawl, so it adds no wall-clock time to a lead. Any failure returns None
and the scorer falls back to the TTFB / page-size rule.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app import cache
from app.config import get_settings

log = logging.getLogger(__name__)

ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


def parse(payload: dict[str, Any]) -> int | None:
    score = (((payload.get("lighthouseResult") or {}).get("categories") or {}).get("performance") or {}).get(
        "score"
    )
    return round(float(score) * 100) if isinstance(score, int | float) else None


async def mobile_score(url: str | None) -> int | None:
    key = get_settings().pagespeed_api_key
    if not key or not url:
        return None
    ckey = cache.key_for("psi", url)
    hit = await cache.get(ckey)
    if hit is not None:
        return hit.get("score")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=5.0)) as c:
            r = await c.get(
                ENDPOINT, params={"url": url, "strategy": "mobile", "category": "performance", "key": key}
            )
        if r.status_code != 200:
            log.info("PageSpeed %s for %s", r.status_code, url)
            return None
        score = parse(r.json())
    except (httpx.HTTPError, ValueError) as e:
        log.info("PageSpeed failed for %s: %s", url, e)
        return None
    await cache.set(ckey, {"score": score}, cache.TTL["crawl"])
    return score
