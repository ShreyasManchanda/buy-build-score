from __future__ import annotations

import json

import httpx
import pytest
import respx

from app.integrations import nominatim, osm, places
from app.pipeline import dedup
from app.pipeline.csv_import import CsvError, map_headers, parse_csv
from app.schemas import GeoPoint

from .conftest import FIXTURES

GEO = GeoPoint(lat=39.9612, lng=-82.9988, display_name="Columbus, Ohio", country_code="US")


# ---------------------------------------------------------------- Overpass


def test_overpass_fixture_parses_into_companies() -> None:
    payload = json.loads((FIXTURES / "overpass_hvac.json").read_text())
    out = osm.parse(payload, limit=60)
    names = [c.name for c in out]
    # nameless dropped, duplicate element id dropped, website-less sorted last
    assert names == [
        "Buckeye Heating & Cooling",
        "Dublin Air Conditioning & Furnace",
        "Kessler & Sons Mechanical",
        "Short North Heating",
    ]
    buckeye = out[0]
    assert buckeye.osm_id == "node/1001"
    assert buckeye.start_date == "1984"
    assert buckeye.address == "1450 Parsons Avenue, Columbus, OH 43206"
    assert (buckeye.lat, buckeye.lng) == (39.9612, -82.9988)
    dublin = out[1]
    assert dublin.website == "http://dublinair.com"
    assert dublin.start_date == "1979"
    assert (dublin.lat, dublin.lng) == (40.0992, -83.1141)
    kessler = out[2]
    assert kessler.website == "http://kesslermechanical.com"
    assert kessler.start_date is None  # "early 1990s" is not a year
    assert kessler.email == "info@kesslermechanical.com"
    assert out[3].website is None


def test_overpass_query_uses_tags_and_name_regex() -> None:
    q = osm.build_query("HVAC contractors", GEO, radius_km=40, limit=60)
    assert "[out:json][timeout:25];" in q
    assert 'nwr["craft"="hvac"](around:40000,39.961200,-82.998800);' in q
    assert 'nwr["name"~"hvac|heating|air ?condition|furnace|mechanical",i]["website"]' in q
    assert q.rstrip().endswith("out center tags 180;")


def test_overpass_query_falls_back_to_keyword_regex() -> None:
    q = osm.build_query("pool installers", GEO, radius_km=10, limit=20)
    assert '"craft"' not in q
    assert 'nwr["name"~"pool|installers",i]["website"]' in q


@respx.mock
async def test_overpass_falls_back_through_mirrors() -> None:
    respx.post("https://overpass-api.de/api/interpreter").mock(return_value=httpx.Response(504))
    respx.post("https://maps.mail.ru/osm/tools/overpass/api/interpreter").mock(
        side_effect=httpx.ReadTimeout("slow")
    )
    payload = json.loads((FIXTURES / "overpass_hvac.json").read_text())
    last = respx.post("https://overpass.private.coffee/api/interpreter").mock(
        return_value=httpx.Response(200, json=payload)
    )
    out = await osm.discover("hvac", GEO, 40, 60)
    assert len(out) == 4 and last.called
    assert out[0].raw["matched_by"] == "tag"


def test_name_only_match_with_other_category_is_dropped() -> None:
    payload = {
        "elements": [
            {"type": "node", "id": 1, "tags": {"name": "Joe's Auto Repair", "shop": "car_repair"}},
            {
                "type": "node",
                "id": 2,
                "tags": {
                    "name": "Cheap Auto Insurance",
                    "office": "insurance",
                    "website": "https://x.example",
                },
            },
            {
                "type": "node",
                "id": 3,
                "tags": {"name": "Pins Mechanical", "amenity": "bar", "website": "https://pins.example"},
            },
            {"type": "node", "id": 4, "tags": {"name": "Ace Automotive", "website": "https://ace.example"}},
        ]
    }
    names = [c.name for c in osm.parse(payload, 60, "auto repair")]
    assert names == ["Ace Automotive", "Joe's Auto Repair"]


# ---------------------------------------------------------------- Nominatim + Places


@respx.mock
async def test_nominatim_geocode_and_cache() -> None:
    route = respx.get("https://nominatim.openstreetmap.org/search").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "lat": "39.9622601",
                    "lon": "-83.0007065",
                    "display_name": "Columbus, Franklin County, Ohio, United States",
                    "address": {"city": "Columbus", "state": "Ohio", "country_code": "us"},
                }
            ],
        )
    )
    g = await nominatim.geocode("Columbus, OH")
    assert g.country_code == "US" and g.city == "Columbus" and round(g.lat, 2) == 39.96
    await nominatim.geocode("columbus, oh ")  # cached: same key after normalisation
    assert route.call_count == 1
    assert "BuyBuildScoreBot" in route.calls[0].request.headers["user-agent"]


@respx.mock
async def test_nominatim_no_result_raises() -> None:
    respx.get("https://nominatim.openstreetmap.org/search").mock(return_value=httpx.Response(200, json=[]))
    with pytest.raises(nominatim.GeocodeError):
        await nominatim.geocode("Nowhereville")


def test_places_parse() -> None:
    c = places.parse_place(
        {
            "id": "ChIJ123",
            "displayName": {"text": "Buckeye Heating & Cooling"},
            "formattedAddress": "1450 Parsons Ave, Columbus, OH 43206, USA",
            "location": {"latitude": 39.94, "longitude": -82.99},
            "websiteUri": "https://buckeyehvac.com/",
            "nationalPhoneNumber": "(614) 555-0101",
            "rating": 4.7,
            "userRatingCount": 212,
            "businessStatus": "OPERATIONAL",
            "reviews": [{"publishTime": "2026-09-01T10:00:00Z"}, {"publishTime": "2025-01-01T10:00:00Z"}],
        }
    )
    assert (c.city, c.region, c.postcode) == ("Columbus", "OH", "43206")
    assert c.review_count == 212 and c.rating == 4.7
    assert c.newest_review_at is not None and c.newest_review_at.year == 2026
    assert c.raw["has_street"] is True


# ---------------------------------------------------------------- normalisation + dedup


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://WWW.BuckeyeHVAC.com/about-us?x=1", "buckeyehvac.com"),
        ("buckeyehvac.com", "buckeyehvac.com"),
        ("http://shop.buckeyehvac.co.uk/", "shop.buckeyehvac.co.uk"),
        ("https://m.example.org", "example.org"),
        ("https://www.facebook.com/buckeyehvac", None),
        ("https://kessler.wixsite.com/home", "kessler.wixsite.com"),
        ("not a url", None),
        (None, None),
    ],
)
def test_normalize_domain(url: str | None, expected: str | None) -> None:
    assert dedup.normalize_domain(url) == expected


def test_normalize_phone_and_name() -> None:
    assert dedup.normalize_phone("(614) 555-0101") == "+16145550101"
    assert dedup.normalize_phone("+1 614 555 0101") == "+16145550101"
    assert dedup.normalize_phone("12") is None
    assert dedup.normalize_name("Buckeye Heating & Cooling, LLC") == "buckeye heating cooling"
    assert dedup.normalize_name("Reilly Plumbing Co.") == "reilly plumbing"


def test_csv_25_rows_with_6_planted_duplicates_dedups_to_19() -> None:
    accepted, rejected, mapping = parse_csv((FIXTURES / "dedup_25.csv").read_bytes())
    assert len(accepted) == 25 and rejected == []
    assert mapping["name"] == "Company Name" and mapping["postcode"] == "Zip Code"
    out = dedup.dedup(accepted)
    assert len(out) == 19
    by_name = {c.name: c for c in out}
    buckeye = by_name["Buckeye Heating & Cooling LLC"]
    assert buckeye.domain == "buckeyehvac.com"
    assert buckeye.merged_from == ["buckeyehvac.com"]
    # phone-only duplicate keeps the more complete record (with website) and its name
    gv = by_name["German Village Auto Repair"]
    assert gv.domain == "gvautorepair.com" and gv.merged_from == ["GV Auto Repair"]
    # fuzzy name + same postcode (ZIP+4 normalised)
    assert "Groveport Heating Company" in by_name["Groveport Heating Co"].merged_from
    assert "Kessler and Sons Mechanical Inc" in by_name["Kessler & Sons Mechanical"].merged_from
    # no record lost its data
    assert all(c.phone_e164 for c in out)


def test_fuzzy_name_needs_same_postcode_and_compatible_domain() -> None:
    from app.schemas import CompanyIn

    a = CompanyIn(name="Acme Plumbing", postcode="43215", website="acmeplumbing.com")
    b = CompanyIn(name="Acme Plumbing LLC", postcode="43016")
    c = CompanyIn(name="Acme Plumbing", postcode="43215", website="acme-plumbing-oh.com")
    assert len(dedup.dedup([a, b])) == 2  # different postcode
    assert len(dedup.dedup([a, c])) == 2  # two different known domains


def test_drop_chains_uses_generic_signals_only() -> None:
    from app.pipeline.discover import drop_chains
    from app.schemas import CompanyIn

    rows = [
        CompanyIn(name="Valvoline Instant Oil Change", website="https://store.vioc.com/oh/columbus"),
        CompanyIn(name="Midas", website="https://midas.com", raw={"brand": "Midas"}),
        *[CompanyIn(name=f"Chain #{i}", website=f"https://chain-example.com/loc/{i}") for i in range(3)],
        CompanyIn(name="Jim's Automotive Electric", website="https://jaeservice.com"),
        CompanyIn(name="No Site Garage"),
    ]
    kept, dropped = drop_chains(rows)
    assert [c.name for c in kept] == ["Jim's Automotive Electric", "No Site Garage"]
    assert dropped == 5


def test_csv_rejects_rows_without_site_or_name_city() -> None:
    data = b"Company,City,Website\nGood Co,Columbus,\nNo City Co,,\n,,example.com\n"
    accepted, rejected, _ = parse_csv(data)
    assert [c.name for c in accepted] == ["Good Co", "example.com"]
    assert rejected[0]["line"] == 3


def test_csv_requires_known_columns_and_size() -> None:
    with pytest.raises(CsvError):
        parse_csv(b"foo,bar\n1,2\n")
    with pytest.raises(CsvError) as e:
        parse_csv(b"x" * (2 * 1024 * 1024 + 1))
    assert e.value.status == 413


def test_header_aliases_case_insensitive() -> None:
    m = map_headers(["COMPANY WEBSITE", "Business Name", "phone_number", "Location"])
    assert m == {
        "name": "Business Name",
        "website": "COMPANY WEBSITE",
        "phone": "phone_number",
        "location": "Location",
    }
