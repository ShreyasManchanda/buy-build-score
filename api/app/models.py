"""ORM models mirroring SPEC.md "Data model" (plus the small additions logged in DECISIONS.md)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        CheckConstraint("source IN ('thesis','csv','demo')", name="runs_source_check"),
        CheckConstraint(
            "status IN ('queued','discovering','crawling','scoring','done','failed')",
            name="runs_status_check",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    query: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    preset: Mapped[str] = mapped_column(Text, nullable=False, server_default="searcher")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    counts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    # Discovered + deduped company ids, so a partial run can resume with only unscored companies.
    plan: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # Upstream warnings shown as a banner (e.g. "Places quota hit — switched to OSM").
    warnings: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="osm")  # 'osm' | 'places' | 'csv'
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    leads: Mapped[list[Lead]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint(
            "crawl_status IN ('ok','partial','blocked_robots','unreachable','no_site')",
            name="companies_crawl_status_check",
        ),
        Index("companies_phone_idx", "phone_e164"),
        Index(
            "companies_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    domain: Mapped[str | None] = mapped_column(Text, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    phone_e164: Mapped[str | None] = mapped_column(Text)
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    postcode: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    place_id: Mapped[str | None] = mapped_column(Text, unique=True)
    osm_id: Mapped[str | None] = mapped_column(Text, unique=True)
    rating: Mapped[Decimal | None] = mapped_column(Numeric(2, 1))
    review_count: Mapped[int | None] = mapped_column(Integer)
    founded_year: Mapped[int | None] = mapped_column(Integer)
    owner_name: Mapped[str | None] = mapped_column(Text)
    crawl_status: Mapped[str | None] = mapped_column(Text)
    crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    evidence: Mapped[list[Evidence]] = relationship(back_populates="company", cascade="all, delete-orphan")


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        CheckConstraint("durability BETWEEN 0 AND 100", name="leads_durability_check"),
        CheckConstraint("succession BETWEEN 0 AND 100", name="leads_succession_check"),
        CheckConstraint("upside BETWEEN 0 AND 100", name="leads_upside_check"),
        CheckConstraint(
            "email_status IN ('valid_mx','no_mx','invalid','none')", name="leads_email_status_check"
        ),
        UniqueConstraint("run_id", "company_id", name="leads_run_company_key"),
        Index("leads_run_idx", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id"), nullable=False
    )
    durability: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    succession: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    upside: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    coverage: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    email: Mapped[str | None] = mapped_column(Text)
    email_status: Mapped[str | None] = mapped_column(Text)
    phone_valid: Mapped[bool | None] = mapped_column(Boolean)
    feedback: Mapped[int | None] = mapped_column(SmallInteger)
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hubspot_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped[Run] = relationship(back_populates="leads")
    company: Mapped[Company] = relationship()


class Evidence(Base):
    __tablename__ = "evidence"
    __table_args__ = (
        CheckConstraint(
            "dimension IN ('durability','succession','upside')", name="evidence_dimension_check"
        ),
        CheckConstraint(
            "extractor IN ('rule','llm','places','osm','whois','http')", name="evidence_extractor_check"
        ),
        UniqueConstraint("company_id", "signal", name="evidence_company_signal_key"),
        Index("evidence_company_idx", "company_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )
    dimension: Mapped[str] = mapped_column(Text, nullable=False)
    signal: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str | None] = mapped_column(Text)
    points: Mapped[Decimal] = mapped_column(Numeric(4, 1), nullable=False)
    confidence: Mapped[Decimal] = mapped_column(Numeric(3, 2), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str | None] = mapped_column(String(200))
    extractor: Mapped[str] = mapped_column(Text, nullable=False)

    company: Mapped[Company] = relationship(back_populates="evidence")


class Cache(Base):
    __tablename__ = "cache"
    __table_args__ = (Index("cache_expires_idx", "expires_at"),)

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
