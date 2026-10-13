from httpx import ASGITransport, AsyncClient

from app.config import normalize_db_url
from app.main import app


def test_neon_url_is_translated_for_asyncpg() -> None:
    url, args = normalize_db_url(
        "postgresql://u:p@ep-x-pooler.c-7.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    )
    assert url == "postgresql+asyncpg://u:p@ep-x-pooler.c-7.us-east-2.aws.neon.tech/neondb"
    assert args == {"ssl": "require"}


def test_local_url_has_no_ssl() -> None:
    url, args = normalize_db_url("postgresql+asyncpg://postgres:postgres@localhost:5432/bbs")
    assert url == "postgresql+asyncpg://postgres:postgres@localhost:5432/bbs"
    assert args == {}


async def test_healthz_shape_and_docs() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/healthz")
        assert r.status_code == 200
        body = r.json()
        assert set(body) >= {"ok", "db", "mode"}
        assert (await c.get("/api/v1/openapi.json")).status_code == 200


async def test_unknown_route_is_problem_json() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.get("/api/v1/nope")
        assert r.status_code == 404
        assert r.headers["content-type"].startswith("application/problem+json")
