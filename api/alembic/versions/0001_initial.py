"""initial schema: runs, companies, leads, evidence, cache

Revision ID: 0001
Revises:
Create Date: 2026-10-13
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        """
        CREATE TABLE runs (
          id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          source        text NOT NULL,
          query         jsonb NOT NULL,
          preset        text NOT NULL DEFAULT 'searcher',
          status        text NOT NULL DEFAULT 'queued',
          counts        jsonb NOT NULL DEFAULT '{}'::jsonb,
          plan          jsonb NOT NULL DEFAULT '[]'::jsonb,
          warnings      jsonb NOT NULL DEFAULT '[]'::jsonb,
          mode          text NOT NULL DEFAULT 'osm',
          error         text,
          created_at    timestamptz NOT NULL DEFAULT now(),
          started_at    timestamptz,
          finished_at   timestamptz,
          CONSTRAINT runs_source_check CHECK (source IN ('thesis','csv','demo')),
          CONSTRAINT runs_status_check
            CHECK (status IN ('queued','discovering','crawling','scoring','done','failed'))
        )
        """
    )
    op.execute(
        """
        CREATE TABLE companies (
          id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          domain          text UNIQUE,
          name            text NOT NULL,
          phone_e164      text,
          address         text,
          city            text, region text, postcode text, country text,
          lat             double precision, lng double precision,
          place_id        text UNIQUE,
          osm_id          text UNIQUE,
          rating          numeric(2,1),
          review_count    int,
          founded_year    int,
          owner_name      text,
          crawl_status    text,
          crawled_at      timestamptz,
          raw             jsonb NOT NULL DEFAULT '{}'::jsonb,
          CONSTRAINT companies_crawl_status_check
            CHECK (crawl_status IN ('ok','partial','blocked_robots','unreachable','no_site'))
        )
        """
    )
    op.execute("CREATE INDEX companies_phone_idx ON companies (phone_e164)")
    op.execute("CREATE INDEX companies_name_trgm ON companies USING gin (name gin_trgm_ops)")
    op.execute(
        """
        CREATE TABLE leads (
          id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
          run_id         uuid NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
          company_id     uuid NOT NULL REFERENCES companies(id),
          durability     smallint NOT NULL,
          succession     smallint NOT NULL,
          upside         smallint NOT NULL,
          coverage       numeric(3,2) NOT NULL,
          email          text,
          email_status   text,
          phone_valid    boolean,
          feedback       smallint,
          exported_at    timestamptz,
          hubspot_id     text,
          created_at     timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT leads_durability_check CHECK (durability BETWEEN 0 AND 100),
          CONSTRAINT leads_succession_check CHECK (succession BETWEEN 0 AND 100),
          CONSTRAINT leads_upside_check CHECK (upside BETWEEN 0 AND 100),
          CONSTRAINT leads_email_status_check
            CHECK (email_status IN ('valid_mx','no_mx','invalid','none')),
          CONSTRAINT leads_run_company_key UNIQUE (run_id, company_id)
        )
        """
    )
    op.execute("CREATE INDEX leads_run_idx ON leads (run_id)")
    op.execute(
        """
        CREATE TABLE evidence (
          id          bigserial PRIMARY KEY,
          company_id  uuid NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
          dimension   text NOT NULL,
          signal      text NOT NULL,
          value       text,
          points      numeric(4,1) NOT NULL,
          confidence  numeric(3,2) NOT NULL,
          source_url  text,
          snippet     varchar(200),
          extractor   text NOT NULL,
          CONSTRAINT evidence_dimension_check CHECK (dimension IN ('durability','succession','upside')),
          CONSTRAINT evidence_extractor_check
            CHECK (extractor IN ('rule','llm','places','osm','whois','http')),
          CONSTRAINT evidence_company_signal_key UNIQUE (company_id, signal)
        )
        """
    )
    op.execute("CREATE INDEX evidence_company_idx ON evidence (company_id)")
    op.execute(
        """
        CREATE TABLE cache (
          key         text PRIMARY KEY,
          value       jsonb NOT NULL,
          expires_at  timestamptz NOT NULL
        )
        """
    )
    op.execute("CREATE INDEX cache_expires_idx ON cache (expires_at)")


def downgrade() -> None:
    for t in ("cache", "evidence", "leads", "companies", "runs"):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
