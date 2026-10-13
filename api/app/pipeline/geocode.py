from __future__ import annotations

from app.integrations import nominatim
from app.schemas import GeoPoint

GeocodeError = nominatim.GeocodeError


async def geocode(location: str) -> GeoPoint:
    return await nominatim.geocode(location)
