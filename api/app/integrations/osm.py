"""OpenStreetMap Overpass discovery (default, free, no key)."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from app import cache, configs, net
from app.schemas import CompanyIn, GeoPoint

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 502, 503, 504}


class OverpassError(Exception):
    pass


def match_industry(industry: str) -> tuple[str | None, dict[str, Any] | None]:
    text = industry.lower()
    for key, spec in configs.osm_tags()["industries"].items():
        if any(alias in text for alias in spec["aliases"]):
            return key, spec
    return None, None


def keyword_regex(industry: str) -> str:
    words = [re.escape(w) for w in re.findall(r"[a-z0-9]+", industry.lower()) if len(w) > 2]
    return "|".join(words) or re.escape(industry.lower())


def build_query(industry: str, geo: GeoPoint, radius_km: int, limit: int, expand: bool = False) -> str:
    _, spec = match_industry(industry)
    around = f"(around:{int(radius_km * 1000)},{geo.lat:.6f},{geo.lng:.6f})"
    lines: list[str] = []
    if spec:
        lines += [f"  nwr[{tag}]{around};" for tag in spec["tags"]]
        name_regex = spec["name_regex"]
        if expand:
            name_regex = f"{name_regex}|{keyword_regex(industry)}"
    else:
        name_regex = keyword_regex(industry)
    name_regex = name_regex.replace('"', "")
    lines.append(f'  nwr["name"~"{name_regex}",i]["website"]{around};')
    # Over-fetch: rows without a website are kept but sorted last, so ask for more than we keep.
    body = "\n".join(lines)
    return f"[out:json][timeout:25];\n(\n{body}\n);\nout center tags {limit * 3};"


def _website(tags: dict[str, str]) -> str | None:
    url = tags.get("website") or tags.get("contact:website") or tags.get("url")
    if not url:
        return None
    url = url.strip().split(";")[0].strip()
    if not re.match(r"^https?://", url, re.I):
        url = "http://" + url
    return url


def _year(start_date: str | None) -> str | None:
    if not start_date:
        return None
    m = re.search(r"\b(1[89]\d\d|20\d\d)\b", start_date)
    return m.group(1) if m else None


CATEGORY_KEYS = ("shop", "amenity", "office", "craft", "healthcare", "leisure", "tourism", "club")


def _tag_pairs(spec_tags: list[str]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for t in spec_tags:
        m = re.match(r'^"([^"]+)"="([^"]+)"$', t)
        if m:
            pairs.add((m.group(1), m.group(2)))
    return pairs


def parse(payload: dict[str, Any], limit: int, industry: str | None = None) -> list[CompanyIn]:
    """Elements -> companies. A row found only by the name regex that carries a *different*
    category tag (an insurance office named "...Auto...", a bar named "...Mechanical") is dropped."""
    _, spec = match_industry(industry) if industry else (None, None)
    wanted = _tag_pairs(spec["tags"]) if spec else set()
    out: list[tuple[bool, CompanyIn]] = []
    seen: set[str] = set()
    for el in payload.get("elements", []):
        tags: dict[str, str] = el.get("tags") or {}
        name = (tags.get("name") or "").strip()
        if not name:
            continue
        osm_id = f"{el.get('type')}/{el.get('id')}"
        if osm_id in seen:
            continue
        seen.add(osm_id)
        by_tag = any(tags.get(k) == v for k, v in wanted)
        if wanted and not by_tag and any(k in tags for k in CATEGORY_KEYS):
            continue
        lat = el.get("lat") if "lat" in el else (el.get("center") or {}).get("lat")
        lng = el.get("lon") if "lon" in el else (el.get("center") or {}).get("lon")
        street = " ".join(p for p in (tags.get("addr:housenumber"), tags.get("addr:street")) if p)
        city = tags.get("addr:city")
        region = tags.get("addr:state")
        postcode = tags.get("addr:postcode")
        region_line = f"{region or ''} {postcode or ''}".strip()
        address = ", ".join(p for p in (street, city, region_line) if p) or None
        company = CompanyIn(
            name=name,
            website=_website(tags),
            phone=tags.get("phone") or tags.get("contact:phone"),
            email=tags.get("email") or tags.get("contact:email"),
            address=address,
            city=city,
            region=region,
            postcode=postcode,
            country=tags.get("addr:country"),
            lat=lat,
            lng=lng,
            osm_id=osm_id,
            start_date=_year(tags.get("start_date")),
            source="osm",
            raw={
                "brand": tags.get("brand") or tags.get("brand:wikidata"),
                "osm_street": street or None,
                "opening_hours": tags.get("opening_hours"),
                "start_date_raw": tags.get("start_date"),
                "matched_by": "tag" if by_tag else "name",
            },
        )
        out.append((by_tag, company))
    # Website first (we can only score what we can read), then tag matches, stable otherwise.
    out.sort(key=lambda pair: (pair[1].website is None, not pair[0]))
    return [c for _, c in out][:limit]


async def _post(endpoint: str, query: str) -> httpx.Response:
    await net.api_throttle.wait(httpx.URL(endpoint).host)
    # Query asks the server for [timeout:25]; allow a little transfer time on top.
    async with net.client(timeout=httpx.Timeout(28.0, connect=5.0)) as c:
        return await c.post(endpoint, data={"data": query})


HEDGE_S = 3.0  # start the next mirror if the previous one hasn't answered within this
RETRY_WAIT_S = 10.0
DISCOVERY_BUDGET_S = 60.0


async def _attempt(ep: str, query: str, delay: float, errors: list[str]) -> dict[str, Any] | None:
    await asyncio.sleep(delay)
    try:
        r = await _post(ep, query)
    except httpx.HTTPError as e:
        errors.append(f"{httpx.URL(ep).host}: {e.__class__.__name__}")
        return None
    if r.status_code != 200:
        errors.append(f"{httpx.URL(ep).host}: HTTP {r.status_code}")
        return None
    data: dict[str, Any] = r.json()
    return data


async def _hedged(endpoints: list[str], query: str, errors: list[str]) -> dict[str, Any] | None:
    """Primary first; each mirror joins HEDGE_S later. First success wins, the rest are cancelled.
    One query hits at most len(endpoints) servers, and only when the earlier ones are slow or failing."""
    tasks = [asyncio.create_task(_attempt(ep, query, i * HEDGE_S, errors)) for i, ep in enumerate(endpoints)]
    try:
        for fut in asyncio.as_completed(tasks):
            result = await fut
            if result is not None:
                return result
        return None
    finally:
        for t in tasks:
            t.cancel()


async def fetch(query: str) -> dict[str, Any]:
    cfg = configs.osm_tags()
    endpoints = [cfg["endpoint"], *cfg.get("fallback_endpoints", [])]
    errors: list[str] = []

    async def go() -> dict[str, Any]:
        for attempt in range(2):
            result = await _hedged(endpoints, query, errors)
            if result is not None:
                return result
            if attempt == 0:
                log.warning("Overpass busy (%s); retrying once in %.0f s", "; ".join(errors), RETRY_WAIT_S)
                await asyncio.sleep(RETRY_WAIT_S)
        raise OverpassError(
            f"OpenStreetMap Overpass is busy right now ({'; '.join(errors[-3:])}). Try again shortly."
        )

    try:
        return await asyncio.wait_for(go(), DISCOVERY_BUDGET_S)
    except TimeoutError as e:
        raise OverpassError("OpenStreetMap Overpass didn't answer within 60 s. Try again shortly.") from e


async def discover(
    industry: str, geo: GeoPoint, radius_km: int, limit: int, expand: bool = False
) -> list[CompanyIn]:
    query = build_query(industry, geo, radius_km, limit, expand)
    key = cache.key_for("osm", query)
    payload = await cache.get_or_set(key, cache.TTL["osm"], lambda: fetch(query))
    return parse(payload, limit, industry)
