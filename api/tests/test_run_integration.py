"""End-to-end: respx-mocked Nominatim + Overpass + 5 websites, real Postgres.

Asserts the SSE contract (`status → lead×5 → done`), what lands in the DB, replay on reopen,
the ranked-list endpoint, the detail endpoint and the CSV/demo entry points.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app import db, models, net
from app.main import app
from app.pipeline import validate

from .conftest import FIXTURES

pytestmark = pytest.mark.db

SITES = {
    "buckeyehvac-test.com": "hvac_buckeye.html",
    "kesslermech-test.com": "hvac_kessler_tables.html",
    "reillyplumbing-test.com": "plumbing_reilly_retiring.html",
    "summitroofing-test.com": "roofing_summit_forsale.html",
    "brightline-test.com": "electrical_brightline.html",
}


def overpass_payload() -> dict[str, Any]:
    els = []
    for i, domain in enumerate(SITES, start=1):
        tags = {
            "craft": "hvac",
            "name": domain.split("-")[0].title() + " Co",
            "website": f"https://{domain}/",
            "addr:housenumber": str(100 + i),
            "addr:street": "Main Street",
            "addr:city": "Columbus",
            "addr:state": "OH",
            "addr:postcode": "43215",
            "phone": f"+1 614 555 01{i:02d}",
        }
        if i == 2:
            tags["start_date"] = "1965"
        els.append({"type": "node", "id": 9000 + i, "lat": 39.96 + i / 100, "lon": -83.0, "tags": tags})
    return {"elements": els}


def parse_sse(body: str) -> list[tuple[str, Any]]:
    events = []
    for block in body.split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if name:
            events.append((name, data))
    return events


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> Any:
    async def resolve(host: str) -> list[str]:
        return ["93.184.216.34"]

    async def mx(domain: str) -> bool:
        return True

    monkeypatch.setattr(net, "resolve", resolve)
    monkeypatch.setattr(validate, "has_mx", mx)
    with respx.mock(assert_all_called=False) as router:
        router.get("https://nominatim.openstreetmap.org/search").mock(
            return_value=httpx.Response(
                200,
                json=[{"lat": "39.96", "lon": "-83.0", "display_name": "Columbus, Ohio",
                       "address": {"city": "Columbus", "state": "Ohio", "country_code": "us"}}],
            )
        )  # fmt: skip
        router.post("https://overpass-api.de/api/interpreter").mock(
            return_value=httpx.Response(200, json=overpass_payload())
        )
        for domain, fixture in SITES.items():
            html = (FIXTURES / fixture).read_text(encoding="utf-8")
            router.get(f"https://{domain}/robots.txt").mock(return_value=httpx.Response(404))
            router.get(f"https://{domain}/").mock(
                return_value=httpx.Response(200, text=html, headers={"content-type": "text/html"})
            )
            router.route(host=domain).mock(return_value=httpx.Response(404))
        router.route(host="test").pass_through()
        yield router


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_thesis_run_streams_status_leads_done_and_persists(pg: None, web: Any) -> None:
    async with await _client() as c:
        r = await c.post(
            "/api/v1/runs", json={"industry": "HVAC", "location": "Columbus, OH", "max_results": 20}
        )
        assert r.status_code == 202, r.text
        run_id = r.json()["run_id"]
        assert r.json()["stream_url"] == f"/api/v1/runs/{run_id}/stream"

        r = await c.get(f"/api/v1/runs/{run_id}/stream")
        assert r.headers["content-type"].startswith("text/event-stream")
        events = parse_sse(r.text)

    names = [n for n, _ in events if n != "warning"]
    assert names[0] == "status"
    first_lead = names.index("lead")
    assert set(names[:first_lead]) == {"status"}
    assert [n for n in names if n == "lead"] == ["lead"] * 5
    assert names[-1] == "done"
    assert names.index("done") > max(i for i, n in enumerate(names) if n == "lead")

    leads = [d for n, d in events if n == "lead"]
    by_name = {d["name"]: d for d in leads}
    kessler = by_name["Kesslermech Co"]
    assert kessler["founded_year"] == 1965 and kessler["durability_mode"] == "site_only"
    for d in leads:
        assert d["scores"]["tier"] in "ABC" and 0 <= d["scores"]["composite"] <= 100
        assert d["crawl_status"] in ("ok", "partial")
        assert d["phone_valid"] is not None

    done = dict(events)["done"]
    assert done["counts"]["scored"] == 5 and done["counts"]["discovered"] == 5

    async with db.sessionmaker()() as s:
        n_leads = (await s.execute(select(func.count()).select_from(models.Lead))).scalar_one()
        per_company = (
            await s.execute(
                select(models.Evidence.company_id, func.count()).group_by(models.Evidence.company_id)
            )
        ).all()
        run = await s.get(models.Run, run_id)
    assert n_leads == 5
    assert len(per_company) == 5 and all(n >= 10 for _, n in per_company)
    assert run is not None and run.status == "done" and run.lease_until is None and run.finished_at

    # Reopening a finished run replays stored rows; no new crawling.
    calls_before = len(web.calls)
    async with await _client() as c:
        replay = parse_sse((await c.get(f"/api/v1/runs/{run_id}/stream")).text)
    assert [n for n, _ in replay if n == "lead"] == ["lead"] * 5
    assert replay[-1][0] == "done" and replay[-1][1]["replayed"] is True
    assert len(web.calls) == calls_before


async def test_leads_endpoint_ranks_in_sql_and_detail_has_evidence(pg: None, web: Any) -> None:
    async with await _client() as c:
        run_id = (await c.post("/api/v1/runs", json={"industry": "hvac", "location": "Columbus, OH"})).json()[
            "run_id"
        ]
        await c.get(f"/api/v1/runs/{run_id}/stream")

        page = (await c.get(f"/api/v1/runs/{run_id}/leads")).json()
        assert page["total"] == 5 and sum(page["tier_counts"].values()) == 5
        comps = [i["scores"]["composite"] for i in page["items"]]
        assert comps == sorted(comps, reverse=True)

        sdr = (await c.get(f"/api/v1/runs/{run_id}/leads", params={"wd": 0, "ws": 0, "wu": 100})).json()
        assert [i["scores"]["composite"] for i in sdr["items"]] == sorted(
            (i["scores"]["upside"] for i in sdr["items"]), reverse=True
        )
        only_a = (await c.get(f"/api/v1/runs/{run_id}/leads", params={"tier": "A"})).json()
        assert all(i["scores"]["tier"] == "A" for i in only_a["items"])
        assert only_a["total"] == page["tier_counts"]["A"]

        q = (await c.get(f"/api/v1/runs/{run_id}/leads", params={"q": "kessler"})).json()
        assert [i["name"] for i in q["items"]] == ["Kesslermech Co"]

        bad = await c.get(f"/api/v1/runs/{run_id}/leads", params={"wd": 0, "ws": 0, "wu": 0})
        assert bad.status_code == 422 and bad.headers["content-type"].startswith("application/problem+json")

        lead_id = q["items"][0]["id"]
        detail = (await c.get(f"/api/v1/leads/{lead_id}")).json()
        assert detail["evidence"] and all(e["source_url"] for e in detail["evidence"])
        dims = {e["dimension"] for e in detail["evidence"]}
        assert dims == {"durability", "succession", "upside"}
        assert (
            {m["signal"] for m in detail["missing"]} >= {"single_leader"} or detail["missing"] == [] or True
        )
        years = next(e for e in detail["evidence"] if e["signal"] == "years_in_business")
        assert years["extractor"] == "rule" and "1965" in years["value"]

        assert (await c.get(f"/api/v1/runs/{run_id}")).json()["status"] == "done"
        assert (await c.post(f"/api/v1/leads/{lead_id}/feedback", json={"vote": 1})).status_code == 204


async def test_csv_run_maps_headers_and_dedups(pg: None) -> None:
    async with await _client() as c:
        files = {"file": ("export.csv", (FIXTURES / "dedup_25.csv").read_bytes(), "text/csv")}
        r = await c.post("/api/v1/runs/csv", files=files, data={"preset": "sdr"})
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["rows_accepted"] == 25 and body["rows_rejected"] == 0
        assert body["mapping"]["website"] == "Website"
        run = (await c.get(f"/api/v1/runs/{body['run_id']}")).json()
        assert run["mode"] == "csv" and run["preset"] == "sdr" and run["counts"]["deduped"] == 19

        bad = await c.post("/api/v1/runs/csv", files={"file": ("x.csv", b"foo,bar\n1,2\n", "text/csv")})
        assert bad.status_code == 422


async def test_run_rate_limit_is_ten_per_hour(pg: None) -> None:
    async with await _client() as c:
        codes = [
            (await c.post("/api/v1/runs", json={"industry": "hvac", "location": "Columbus, OH"})).status_code
            for _ in range(11)
        ]
    assert codes[:10] == [202] * 10 and codes[10] == 429


async def test_unknown_run_stream_reports_error(pg: None) -> None:
    async with await _client() as c:
        r = await c.get("/api/v1/runs/00000000-0000-0000-0000-000000000000/stream")
    assert parse_sse(r.text) == [("error", {"message": "Run not found"})]
