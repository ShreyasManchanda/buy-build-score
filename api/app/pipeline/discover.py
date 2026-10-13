"""Discovery: Google Places when a key is set, OpenStreetMap otherwise (and on any Places error)."""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field

from app import configs
from app.config import get_settings
from app.integrations import osm, places
from app.pipeline.dedup import normalize_domain
from app.schemas import CompanyIn, GeoPoint

log = logging.getLogger(__name__)


@dataclass
class Discovery:
    companies: list[CompanyIn]
    mode: str  # 'places' | 'osm'
    warnings: list[str] = field(default_factory=list)
    chains_dropped: int = 0


_CHAIN_SUBDOMAINS = ("locations.", "location.", "store.", "stores.", "local.", "branches.")


def drop_chains(companies: list[CompanyIn]) -> tuple[list[CompanyIn], int]:
    """Remove franchise/chain locations: they aren't owner-operated, so they're noise for a searcher.

    Generic signals only: an OSM `brand`/`brand:wikidata` tag, a store-locator subdomain
    (locations.example.com), or one domain shared by 3+ discovered locations.
    """
    domains = [normalize_domain(c.website) for c in companies]
    per_domain = Counter(d for d in domains if d)
    kept: list[CompanyIn] = []
    for c, d in zip(companies, domains, strict=True):
        if c.raw.get("brand"):
            continue
        if d and (d.startswith(_CHAIN_SUBDOMAINS) or per_domain[d] >= 3):
            continue
        kept.append(c)
    return kept, len(companies) - len(kept)


def related_keywords(industry: str) -> list[str]:
    """Up to 2 related keywords for "Expand" (from the matched industry's aliases)."""
    _, spec = osm.match_industry(industry)
    if not spec:
        return []
    text = industry.lower()
    return [a for a in spec["aliases"] if a not in text][:2]


async def discover(
    industry: str, location: str, geo: GeoPoint, radius_km: int, max_results: int, expand: bool = False
) -> Discovery:
    limit_cap = int(configs.osm_tags()["limits"]["max_limit"])
    warnings: list[str] = []
    if get_settings().has_places:
        try:
            found = await places.discover(industry, location, geo, radius_km, max_results)
            if expand:
                for kw in related_keywords(industry):
                    found += await places.discover(kw, location, geo, radius_km, max_results)
            kept, dropped = drop_chains(found[:limit_cap])
            return Discovery(kept, "places", chains_dropped=dropped)
        except places.PlacesError as e:
            msg = (
                "Google Places quota hit — switched to OpenStreetMap"
                if e.quota
                else f"{e} — switched to OpenStreetMap"
            )
            log.warning(msg)
            warnings.append(msg)
    limit = min(max_results * (3 if expand else 1), limit_cap)
    found = await osm.discover(industry, geo, radius_km, limit * 2, expand=expand)
    kept, dropped = drop_chains(found)
    return Discovery(kept[:limit], "osm", warnings, chains_dropped=dropped)
