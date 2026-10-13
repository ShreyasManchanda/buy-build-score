"""Geocode a plain-text location once per run via Nominatim.

Usage policy: <= 1 req/s, identifying User-Agent, cache results, no autocomplete.
"""

from __future__ import annotations

from typing import Any

from app import cache, net
from app.schemas import GeoPoint

ENDPOINT = "https://nominatim.openstreetmap.org/search"


class GeocodeError(Exception):
    pass


def parse(results: list[dict[str, Any]]) -> GeoPoint | None:
    if not results:
        return None
    r = results[0]
    addr = r.get("address") or {}
    return GeoPoint(
        lat=float(r["lat"]),
        lng=float(r["lon"]),
        display_name=r.get("display_name", ""),
        country_code=(addr.get("country_code") or "").upper() or None,
        city=addr.get("city") or addr.get("town") or addr.get("village") or addr.get("county"),
        region=addr.get("state"),
    )


async def geocode(location: str) -> GeoPoint:
    key = cache.key_for("geo", location.strip().lower())

    async def fetch() -> dict[str, Any] | None:
        await net.api_throttle.wait("nominatim.openstreetmap.org")
        async with net.client() as c:
            r = await c.get(
                ENDPOINT,
                params={"q": location, "format": "jsonv2", "limit": 1, "addressdetails": 1},
            )
            r.raise_for_status()
            point = parse(r.json())
            return point.model_dump() if point else None

    data = await cache.get_or_set(key, cache.TTL["geo"], fetch)
    if not data:
        raise GeocodeError(f"Couldn't find “{location}”. Try “City, State”.")
    return GeoPoint.model_validate(data)
