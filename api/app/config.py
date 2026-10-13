"""All runtime configuration. Every key is optional except DATABASE_URL."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic_settings import BaseSettings, SettingsConfigDict

API_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = API_DIR.parent
APP_DIR = Path(__file__).resolve().parent

# libpq-only query params that asyncpg rejects; we translate sslmode into connect_args.
_LIBPQ_ONLY = {"sslmode", "channel_binding", "options", "target_session_attrs", "gssencmode"}


def normalize_db_url(url: str) -> tuple[str, dict[str, object]]:
    """Return (sqlalchemy asyncpg URL, connect_args) from any Postgres URL Neon/Docker gives us."""
    parts = urlsplit(url.strip())
    scheme = parts.scheme
    if scheme in ("postgres", "postgresql", "postgresql+psycopg", "postgresql+psycopg2"):
        scheme = "postgresql+asyncpg"
    query = dict(parse_qsl(parts.query))
    sslmode = query.get("sslmode") or query.get("ssl")
    kept = {k: v for k, v in query.items() if k not in _LIBPQ_ONLY and k != "ssl"}
    connect_args: dict[str, object] = {}
    wants_ssl = bool(sslmode) and sslmode not in ("disable", "allow", "prefer")
    is_neon = bool(parts.hostname and parts.hostname.endswith(".neon.tech"))
    if wants_ssl or is_neon:
        connect_args["ssl"] = "require"
    new = urlunsplit((scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))
    return new, connect_args


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(REPO_DIR / ".env"), str(API_DIR / ".env")),
        env_file_encoding="utf-8-sig",
        extra="ignore",
    )

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/bbs"
    test_database_url: str = ""  # pytest only: a separate database the integration tests may truncate

    google_places_api_key: str = ""
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    pagespeed_api_key: str = ""
    hubspot_token: str = ""

    crawl_concurrency: int = 20
    crawl_user_agent: str = "BuyBuildScoreBot/0.1 (+https://github.com/ShreyasManchanda/buy-build-score)"
    run_time_budget_seconds: int = 280
    allowed_origins: str = "http://localhost:3000"
    public_app_url: str = ""

    # Rate limits (Postgres-backed)
    runs_per_hour_per_ip: int = 10
    requests_per_minute_per_ip: int = 60

    @property
    def sqlalchemy_url(self) -> str:
        return normalize_db_url(self.database_url)[0]

    @property
    def db_connect_args(self) -> dict[str, object]:
        return normalize_db_url(self.database_url)[1]

    @property
    def has_places(self) -> bool:
        return bool(self.google_places_api_key)

    @property
    def has_llm(self) -> bool:
        return bool(self.gemini_api_key or self.groq_api_key)

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
