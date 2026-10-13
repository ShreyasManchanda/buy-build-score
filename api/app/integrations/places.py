"""Google Places API (New) Text Search — only used when GOOGLE_PLACES_API_KEY is set.

Up to 3 pages x 20 = 60 results per query. Any quota/HTTP error raises PlacesError so the
caller can fall back to OSM and emit a `warning` event.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import httpx

from app import cache, net
from app.config import get_settings
from app.schemas import CompanyIn, GeoPoint

ENDPOINT = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.location",
        "places.websiteUri",
        "places.nationalPhoneNumber",
        "places.rating",
        "places.userRatingCount",
        "places.businessStatus",
        "places.reviews",
        "nextPageToken",
    ]
)

_ADDR = re.compile(
    r"^(?P<street>[^,]+),\s*(?P<city>[^,]+),\s*(?P<region>[A-Z]{2})\s+(?P<postcode>\d{5}(?:-\d{4})?)"
    r"(?:,\s*(?P<country>.+))?$"
)


class PlacesError(Exception):
    def __init__(self, message: str, quota: bool = False) -> None:
        super().__init__(message)
        self.quota = quota


def _newest_review(reviews: list[dict[str, Any]] | None) -> datetime | None:
    times: list[datetime] = []
    for r in reviews or []:
        t = r.get("publishTime")
        if t:
            try:
                times.append(datetime.fromisoformat(t.replace("Z", "+00:00")))
            except ValueError:
                continue
    return max(times) if times else None


def parse_place(p: dict[str, Any]) -> CompanyIn:
    addr = p.get("formattedAddress")
    m = _ADDR.match(addr or "")
    loc = p.get("location") or {}
    return CompanyIn(
        name=(p.get("displayName") or {}).get("text") or "Unknown",
        website=p.get("websiteUri"),
        phone=p.get("nationalPhoneNumber"),
        address=addr,
        city=m.group("city") if m else None,
        region=m.group("region") if m else None,
        postcode=m.group("postcode") if m else None,
        country="US" if m and (m.group("country") or "USA") in ("USA", "United States") else None,
        lat=loc.get("latitude"),
        lng=loc.get("longitude"),
        place_id=p.get("id"),
        rating=p.get("rating"),
        review_count=p.get("userRatingCount"),
        business_status=p.get("businessStatus"),
        newest_review_at=_newest_review(p.get("reviews")),
        source="places",
        raw={"has_street": bool(m)},
    )


async def _page(body: dict[str, Any]) -> dict[str, Any]:
    key = get_settings().google_places_api_key
    async with net.client(timeout=httpx.Timeout(15.0, connect=5.0)) as c:
        r = await c.post(
            ENDPOINT,
            json=body,
            headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": FIELD_MASK},
        )
    if r.status_code == 429 or (r.status_code == 403 and "quota" in r.text.lower()):
        raise PlacesError("Google Places quota hit", quota=True)
    if r.status_code >= 400:
        raise PlacesError(f"Google Places error HTTP {r.status_code}")
    data: dict[str, Any] = r.json()
    return data


async def _search(text: str, geo: GeoPoint, radius_km: int, limit: int) -> list[dict[str, Any]]:
    places: list[dict[str, Any]] = []
    token: str | None = None
    for _ in range(3):
        body: dict[str, Any] = {
            "textQuery": text,
            "pageSize": 20,
            "locationBias": {
                "circle": {
                    "center": {"latitude": geo.lat, "longitude": geo.lng},
                    "radius": float(min(radius_km * 1000, 50000)),
                }
            },
        }
        if token:
            body["pageToken"] = token
        data = await _page(body)
        places += data.get("places", [])
        token = data.get("nextPageToken")
        if not token or len(places) >= limit:
            break
    return places[:limit]


async def discover(
    industry: str, location: str, geo: GeoPoint, radius_km: int, limit: int
) -> list[CompanyIn]:
    if not get_settings().has_places:
        raise PlacesError("no key")
    text = f"{industry} in {location}"
    key = cache.key_for("places", text, round(geo.lat, 3), round(geo.lng, 3), radius_km, limit)
    raw = await cache.get_or_set(key, cache.TTL["places"], lambda: _search(text, geo, radius_km, limit))
    return [parse_place(p) for p in raw]
