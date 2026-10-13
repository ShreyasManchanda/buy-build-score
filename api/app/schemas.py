"""Pydantic v2 schemas shared by pipeline and routes."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Preset = Literal["searcher", "sdr", "caprae"]
Dimension = Literal["durability", "succession", "upside"]
Extractor = Literal["rule", "llm", "places", "osm", "whois", "http"]
Tier = Literal["A", "B", "C"]
CrawlStatus = Literal["ok", "partial", "blocked_robots", "unreachable", "no_site"]


# ---------------------------------------------------------------- discovery


class CompanyIn(BaseModel):
    """A business as discovered (OSM, Places or CSV), before crawling."""

    model_config = ConfigDict(extra="ignore")

    name: str
    website: str | None = None
    domain: str | None = None
    phone: str | None = None
    phone_e164: str | None = None
    email: str | None = None
    address: str | None = None
    city: str | None = None
    region: str | None = None
    postcode: str | None = None
    country: str | None = None
    lat: float | None = None
    lng: float | None = None
    osm_id: str | None = None
    place_id: str | None = None
    rating: float | None = None
    review_count: int | None = None
    business_status: str | None = None
    newest_review_at: datetime | None = None
    start_date: str | None = None
    source: Literal["osm", "places", "csv", "demo"] = "osm"
    raw: dict[str, Any] = Field(default_factory=dict)
    merged_from: list[str] = Field(default_factory=list)

    def ident(self) -> str:
        return self.osm_id or self.place_id or self.domain or self.name


class GeoPoint(BaseModel):
    lat: float
    lng: float
    display_name: str
    country_code: str | None = None
    city: str | None = None
    region: str | None = None


# ---------------------------------------------------------------- runs


class ThesisIn(BaseModel):
    industry: str = Field(min_length=2, max_length=80, examples=["hvac"])
    location: str = Field(min_length=2, max_length=120, examples=["Columbus, OH"])
    radius_km: int = Field(default=40, ge=1, le=100)
    max_results: Literal[20, 40, 60] = 60
    expand: bool = Field(default=False, description="Add up to 2 related keywords (max 180 results)")
    preset: Preset = "searcher"

    @field_validator("industry", "location")
    @classmethod
    def _strip(cls, v: str) -> str:
        return " ".join(v.split())


class RunCreated(BaseModel):
    run_id: uuid.UUID
    stream_url: str


class CsvRunCreated(RunCreated):
    rows_accepted: int
    rows_rejected: int
    rejected: list[dict[str, Any]] = Field(default_factory=list)
    mapping: dict[str, str] = Field(default_factory=dict)


class RunOut(BaseModel):
    id: uuid.UUID
    source: str
    query: dict[str, Any]
    preset: str
    status: str
    mode: str
    counts: dict[str, Any]
    warnings: list[Any]
    error: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


# ---------------------------------------------------------------- evidence + leads


class EvidenceOut(BaseModel):
    id: int | None = None
    dimension: Dimension
    signal: str
    label: str = ""
    value: str | None = None
    points: float
    max_points: float = 0
    confidence: float
    source_url: str | None = None
    snippet: str | None = None
    extractor: Extractor


class Scores(BaseModel):
    durability: int
    succession: int
    upside: int
    composite: int
    tier: Tier
    capped: str | None = None  # 'durability_floor' | 'thin_data' | None


class LeadOut(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    domain: str | None
    website: str | None
    city: str | None
    region: str | None
    phone: str | None
    founded_year: int | None
    owner_name: str | None
    rating: float | None
    review_count: int | None
    scores: Scores
    coverage: float
    thin_data: bool
    top_evidence: list[str]
    email_status: str | None
    phone_valid: bool | None
    crawl_status: str | None
    durability_mode: Literal["full", "site_only"]
    lat: float | None = None
    lng: float | None = None


class MissingSignal(BaseModel):
    dimension: Dimension
    signal: str
    label: str
    max_points: float


class LeadDetail(LeadOut):
    evidence: list[EvidenceOut]
    missing: list[MissingSignal]
    address: str | None
    postcode: str | None
    email: str | None
    owner_title: str | None = None
    owner_source_url: str | None = None
    services: list[str] = Field(default_factory=list)
    tech: list[str] = Field(default_factory=list)
    run_id: uuid.UUID
    place_id: str | None = None
    osm_id: str | None = None


class LeadPage(BaseModel):
    items: list[LeadOut]
    total: int
    tier_counts: dict[str, int] = Field(default_factory=dict)
