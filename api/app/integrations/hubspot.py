"""HubSpot Companies push (P1). Private-app token with crm.objects.companies.read/write and
crm.schemas.companies.write.

- First push creates the "Buy & Build Score" property group and `bbs_*` properties if missing.
- Batch upsert on `domain` in batches of 100.
- HubSpot doesn't enforce unique domains; when a batch fails with "non-unique property domain",
  each row is retried by searching the domain and updating the oldest record by id.
- Partial failures are returned per record; nothing is silently dropped.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

BASE = "https://api.hubapi.com"
GROUP = "buy_build_score"
BATCH = 100

PROPERTIES: list[dict[str, Any]] = [
    {
        "name": "bbs_tier",
        "label": "BBS tier",
        "type": "enumeration",
        "fieldType": "select",
        "options": [{"label": t, "value": t, "displayOrder": i} for i, t in enumerate("ABC")],
    },
    {"name": "bbs_composite", "label": "BBS composite", "type": "number", "fieldType": "number"},
    {"name": "bbs_durability", "label": "BBS durability", "type": "number", "fieldType": "number"},
    {"name": "bbs_succession", "label": "BBS succession", "type": "number", "fieldType": "number"},
    {"name": "bbs_upside", "label": "BBS digital upside", "type": "number", "fieldType": "number"},
    {"name": "bbs_evidence", "label": "BBS evidence", "type": "string", "fieldType": "textarea"},
    {"name": "bbs_run_url", "label": "BBS lead link", "type": "string", "fieldType": "text"},
]


class HubspotNotConfigured(Exception):
    pass


@dataclass
class PushRow:
    lead_id: str
    domain: str | None
    name: str
    phone: str | None
    city: str | None
    state: str | None
    founded_year: int | None
    tier: str
    composite: int
    durability: int
    succession: int
    upside: int
    evidence: list[str]
    run_url: str


@dataclass
class PushResult:
    created: int
    updated: int
    failed: list[dict[str, Any]]


def properties_for(r: PushRow) -> dict[str, Any]:
    props: dict[str, Any] = {
        "domain": r.domain,
        "name": r.name,
        "phone": r.phone,
        "city": r.city,
        "state": r.state,
        "founded_year": str(r.founded_year) if r.founded_year else None,
        "bbs_tier": r.tier,
        "bbs_composite": r.composite,
        "bbs_durability": r.durability,
        "bbs_succession": r.succession,
        "bbs_upside": r.upside,
        "bbs_evidence": "\n".join(r.evidence[:5]),
        "bbs_run_url": r.run_url,
    }
    return {k: v for k, v in props.items() if v not in (None, "")}


def build_inputs(rows: list[PushRow]) -> list[dict[str, Any]]:
    """The batch-upsert `inputs` payload (snapshot-tested)."""
    return [
        {"idProperty": "domain", "id": r.domain, "properties": properties_for(r)} for r in rows if r.domain
    ]


def _client() -> httpx.AsyncClient:
    token = get_settings().hubspot_token
    if not token:
        raise HubspotNotConfigured("Set HUBSPOT_TOKEN to enable HubSpot push.")
    return httpx.AsyncClient(
        base_url=BASE,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        timeout=httpx.Timeout(20.0, connect=5.0),
    )


async def ensure_schema(c: httpx.AsyncClient) -> None:
    r = await c.post(
        "/crm/v3/properties/companies/groups",
        json={"name": GROUP, "label": "Buy & Build Score", "displayOrder": -1},
    )
    if r.status_code not in (200, 201, 409):
        r.raise_for_status()
    for prop in PROPERTIES:
        r = await c.post("/crm/v3/properties/companies", json={**prop, "groupName": GROUP})
        if r.status_code not in (200, 201, 409):
            r.raise_for_status()


async def _update_oldest_by_domain(c: httpx.AsyncClient, row: PushRow) -> str:
    """Fallback for portals that already hold duplicate domains: update the oldest record."""
    r = await c.post(
        "/crm/v3/objects/companies/search",
        json={
            "filterGroups": [
                {"filters": [{"propertyName": "domain", "operator": "EQ", "value": row.domain}]}
            ],
            "sorts": [{"propertyName": "createdate", "direction": "ASCENDING"}],
            "properties": ["domain"],
            "limit": 1,
        },
    )
    r.raise_for_status()
    results = r.json().get("results", [])
    if results:
        cid = results[0]["id"]
        u = await c.patch(f"/crm/v3/objects/companies/{cid}", json={"properties": properties_for(row)})
        u.raise_for_status()
        return "updated"
    n = await c.post("/crm/v3/objects/companies", json={"properties": properties_for(row)})
    n.raise_for_status()
    return "created"


async def push(rows: list[PushRow]) -> tuple[PushResult, dict[str, str]]:
    """Returns the result plus {lead_id: hubspot_company_id} for rows that landed."""
    result = PushResult(created=0, updated=0, failed=[])
    ids: dict[str, str] = {}
    for r in rows:
        if not r.domain:
            result.failed.append(
                {"lead_id": r.lead_id, "domain": None, "reason": "no website domain to upsert on"}
            )
    with_domain = [r for r in rows if r.domain]
    async with _client() as c:
        await ensure_schema(c)
        for i in range(0, len(with_domain), BATCH):
            chunk = with_domain[i : i + BATCH]
            resp = await c.post(
                "/crm/v3/objects/companies/batch/upsert", json={"inputs": build_inputs(chunk)}
            )
            if resp.status_code in (200, 201, 207):
                body = resp.json()
                by_domain = {r.domain: r for r in chunk}
                for item in body.get("results", []):
                    dom = (item.get("properties") or {}).get("domain")
                    if item.get("new"):
                        result.created += 1
                    else:
                        result.updated += 1
                    if dom in by_domain:
                        ids[by_domain[dom].lead_id] = str(item.get("id"))
                for err in body.get("errors", []):
                    result.failed.append(
                        {"lead_id": None, "domain": None, "reason": err.get("message", "error")}
                    )
                continue
            if "non-unique" in resp.text.lower():
                for row in chunk:
                    try:
                        outcome = await _update_oldest_by_domain(c, row)
                        setattr(result, outcome, getattr(result, outcome) + 1)
                    except httpx.HTTPError as e:
                        result.failed.append({"lead_id": row.lead_id, "domain": row.domain, "reason": str(e)})
                continue
            reason = f"HubSpot HTTP {resp.status_code}: {resp.text[:200]}"
            for row in chunk:
                result.failed.append({"lead_id": row.lead_id, "domain": row.domain, "reason": reason})
    return result, ids
