"""SaaSquatch CSV import: case-insensitive header aliases; unmapped columns kept in `raw`."""

from __future__ import annotations

import csv
import io
from typing import Any

from app.schemas import CompanyIn

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 500

ALIASES: dict[str, list[str]] = {
    "name": ["company", "company name", "business name", "name", "organization", "account name"],
    "website": ["website", "domain", "url", "company website", "company domain", "web"],
    "phone": ["phone", "phone number", "company phone", "main phone", "telephone"],
    "city": ["city", "town"],
    "region": ["state", "region", "province", "state/region"],
    "location": ["location", "hq location", "address"],
    "postcode": ["zip", "zip code", "postal code", "postcode"],
    "email": ["company email", "email", "generic email"],
    "revenue_est": ["revenue", "estimated revenue", "annual revenue", "revenue range"],
    "industry": ["industry"],
}


class CsvError(Exception):
    def __init__(self, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.status = status


def _norm(h: str) -> str:
    return " ".join(h.strip().lower().replace("_", " ").split())


def map_headers(headers: list[str]) -> dict[str, str]:
    """Return {our_field: original_header} for the first matching alias of each field."""
    normalized = {_norm(h): h for h in headers if h}
    mapping: dict[str, str] = {}
    for field, aliases in ALIASES.items():
        for alias in aliases:
            if alias in normalized and normalized[alias] not in mapping.values():
                mapping[field] = normalized[alias]
                break
    return mapping


def parse_csv(data: bytes) -> tuple[list[CompanyIn], list[dict[str, Any]], dict[str, str]]:
    if len(data) > MAX_BYTES:
        raise CsvError("CSV is larger than 2 MB.", status=413)
    text = data.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    headers = list(reader.fieldnames or [])
    mapping = map_headers(headers)
    if "website" not in mapping and "name" not in mapping:
        raise CsvError("CSV needs a `website` column, or `company name` plus `city`.")

    accepted: list[CompanyIn] = []
    rejected: list[dict[str, Any]] = []
    for i, row in enumerate(reader, start=2):  # header is line 1
        if i - 1 > MAX_ROWS:
            raise CsvError(f"CSV has more than {MAX_ROWS} rows.", status=413)

        def get(field: str, _row: dict[str, Any] = row) -> str | None:
            h = mapping.get(field)
            v = (_row.get(h) or "").strip() if h else ""
            return v or None

        name, website, city, region = get("name"), get("website"), get("city"), get("region")
        location = get("location")
        if location and not (city and region):
            parts = [p.strip() for p in location.split(",")]
            city = city or (parts[0] if parts else None)
            region = region or (parts[1] if len(parts) > 1 else None)
        if not website and not (name and city):
            rejected.append({"line": i, "reason": "needs website, or company name + city", "row": row})
            continue
        unmapped = {k: v for k, v in row.items() if k and k not in mapping.values() and v}
        accepted.append(
            CompanyIn(
                name=name or (website or "").split("//")[-1].split("/")[0],
                website=website,
                phone=get("phone"),
                email=get("email"),
                city=city,
                region=region,
                postcode=get("postcode"),
                source="csv",
                raw={"csv": unmapped, "revenue_est": get("revenue_est"), "csv_line": i},
            )
        )
    return accepted, rejected, mapping
