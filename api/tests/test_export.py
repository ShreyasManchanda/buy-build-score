from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.config import get_settings
from app.integrations import hubspot
from app.pipeline import validate
from app.routes.export import _cell


def row(domain: str | None = "reillyplumbing.com", lead_id: str = "l1") -> hubspot.PushRow:
    return hubspot.PushRow(
        lead_id=lead_id,
        domain=domain,
        name="Reilly Plumbing Co.",
        phone="+16145550102",
        city="Columbus",
        state="OH",
        founded_year=1972,
        tier="A",
        composite=82,
        durability=89,
        succession=77,
        upside=77,
        evidence=[
            "Exit language: retiring (https://reillyplumbing.com/)",
            "Years in business: 1972 (54 yrs) (https://reillyplumbing.com/)",
        ],
        run_url="https://bbs.example/runs/r1?lead=l1",
    )


def test_hubspot_payload_snapshot() -> None:
    assert hubspot.build_inputs([row(), row(domain=None, lead_id="l2")]) == [
        {
            "idProperty": "domain",
            "id": "reillyplumbing.com",
            "properties": {
                "domain": "reillyplumbing.com",
                "name": "Reilly Plumbing Co.",
                "phone": "+16145550102",
                "city": "Columbus",
                "state": "OH",
                "founded_year": "1972",
                "bbs_tier": "A",
                "bbs_composite": 82,
                "bbs_durability": 89,
                "bbs_succession": 77,
                "bbs_upside": 77,
                "bbs_evidence": "Exit language: retiring (https://reillyplumbing.com/)\n"
                "Years in business: 1972 (54 yrs) (https://reillyplumbing.com/)",
                "bbs_run_url": "https://bbs.example/runs/r1?lead=l1",
            },
        }
    ]
    names = {p["name"] for p in hubspot.PROPERTIES}
    assert names == {"bbs_tier", "bbs_composite", "bbs_durability", "bbs_succession", "bbs_upside", "bbs_evidence",
                     "bbs_run_url"}  # fmt: skip


@pytest.fixture
def token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUBSPOT_TOKEN", "pat-test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@respx.mock
async def test_hubspot_push_upserts_and_creates_schema(token: None) -> None:
    group = respx.post(f"{hubspot.BASE}/crm/v3/properties/companies/groups").mock(
        return_value=httpx.Response(409)
    )
    props = respx.post(f"{hubspot.BASE}/crm/v3/properties/companies").mock(return_value=httpx.Response(201))
    upsert = respx.post(f"{hubspot.BASE}/crm/v3/objects/companies/batch/upsert").mock(
        return_value=httpx.Response(
            200,
            json={"results": [{"id": "901", "new": True, "properties": {"domain": "reillyplumbing.com"}}]},
        )
    )
    result, ids = await hubspot.push([row(), row(domain=None, lead_id="l2")])
    assert (result.created, result.updated) == (1, 0)
    assert result.failed == [{"lead_id": "l2", "domain": None, "reason": "no website domain to upsert on"}]
    assert ids == {"l1": "901"}
    assert group.called and props.call_count == len(hubspot.PROPERTIES)
    sent = json.loads(upsert.calls[0].request.content)
    assert sent["inputs"][0]["idProperty"] == "domain"
    assert upsert.calls[0].request.headers["authorization"] == "Bearer pat-test"


@respx.mock
async def test_hubspot_non_unique_domain_updates_oldest(token: None) -> None:
    respx.post(f"{hubspot.BASE}/crm/v3/properties/companies/groups").mock(return_value=httpx.Response(201))
    respx.post(f"{hubspot.BASE}/crm/v3/properties/companies").mock(return_value=httpx.Response(409))
    respx.post(f"{hubspot.BASE}/crm/v3/objects/companies/batch/upsert").mock(
        return_value=httpx.Response(400, json={"message": "Duplicate: non-unique property domain"})
    )
    search = respx.post(f"{hubspot.BASE}/crm/v3/objects/companies/search").mock(
        return_value=httpx.Response(200, json={"results": [{"id": "111"}]})
    )
    patch = respx.patch(f"{hubspot.BASE}/crm/v3/objects/companies/111").mock(return_value=httpx.Response(200))
    result, _ = await hubspot.push([row()])
    assert (result.created, result.updated, result.failed) == (0, 1, [])
    body = json.loads(search.calls[0].request.content)
    assert body["sorts"] == [{"propertyName": "createdate", "direction": "ASCENDING"}]
    assert patch.called


async def test_hubspot_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HUBSPOT_TOKEN", "")
    get_settings.cache_clear()
    with pytest.raises(hubspot.HubspotNotConfigured):
        await hubspot.push([row()])
    get_settings.cache_clear()


# ---------------------------------------------------------------- validation + csv


async def test_email_status_syntax_and_mx(monkeypatch: pytest.MonkeyPatch) -> None:
    async def mx(domain: str) -> bool | None:
        return {"good.com": True, "nomail.com": False}.get(domain)

    monkeypatch.setattr(validate, "has_mx", mx)
    assert await validate.email_status("office@good.com") == "valid_mx"
    assert await validate.email_status("office@nomail.com") == "no_mx"
    assert await validate.email_status("not an email") == "invalid"
    assert await validate.email_status(None) == "none"
    assert await validate.email_status("x@unknown.com") == "none"  # couldn't check -> never claim valid


def test_phone_validity() -> None:
    assert validate.phone_valid("+16142245566") is True
    assert validate.phone_valid("+11235550101") is False  # no US area code starts with 1
    assert validate.phone_valid(None) is None


@pytest.mark.parametrize(
    ("raw", "out"),
    [
        ("=HYPERLINK(1)", "'=HYPERLINK(1)"),
        ("+SUM(A1:A9)", "'+SUM(A1:A9)"),
        ("-cmd|calc", "'-cmd|calc"),
        ("@x", "'@x"),
        ("+16146180116", "+16146180116"),
        ("+1 (614) 618-0116", "+1 (614) 618-0116"),
        ("-3.5", "-3.5"),
        ("Acme", "Acme"),
        (None, ""),
    ],
)
def test_csv_cells_neutralise_formulas(raw: str | None, out: str) -> None:
    assert _cell(raw) == out


def test_pagespeed_parse() -> None:
    from app.integrations import pagespeed

    assert pagespeed.parse({"lighthouseResult": {"categories": {"performance": {"score": 0.42}}}}) == 42
    assert pagespeed.parse({}) is None


async def test_pagespeed_is_off_without_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations import pagespeed

    monkeypatch.setenv("PAGESPEED_API_KEY", "")
    get_settings.cache_clear()
    assert await pagespeed.mobile_score("https://x.com") is None
    get_settings.cache_clear()
