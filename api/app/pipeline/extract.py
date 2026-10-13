"""Rules first, LLM last: run deterministic extractors, then ask the LLM only for what's still missing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.extractors import Evidence, Pages, run_all
from app.integrations.llm import CONFIDENCE, LlmBatcher, LlmFacts, LlmRequest
from app.pipeline.crawl import CrawlResult


@dataclass
class Extraction:
    facts: dict[str, Evidence]
    pages: Pages
    llm_used: bool = False
    services: list[str] | None = None
    owner_title: str | None = None


def llm_text(pages: Pages) -> tuple[str, str | None]:
    """About/team text first (where owners and founding stories live), then the homepage."""
    ordered = pages.of_kind("about", "team") + pages.of_kind("home") + pages.of_kind("contact")
    text, url = "", None
    for p in ordered:
        if not text:
            url = p.url
        text += p.text + "\n"
        if len(text) >= 6000:
            break
    return text[:6000], url


def merge_llm(facts: dict[str, Evidence], llm: LlmFacts, source_url: str | None) -> list[str]:
    """Add LLM facts only where rules found nothing. Returns the signals filled."""
    filled: list[str] = []
    snip = llm.evidence_quote[:200]
    if llm.founded_year and "founded_year" not in facts:
        facts["founded_year"] = Evidence(
            "founded_year",
            llm.founded_year,
            str(llm.founded_year),
            source_url,
            snippet=snip,
            extractor="llm",
            confidence=CONFIDENCE,
            extra={"method": "llm", "provider": llm.provider},
        )
        filled.append("founded_year")
    if llm.owner_name and "owner_name" not in facts:
        facts["owner_name"] = Evidence(
            "owner_name",
            llm.owner_name,
            llm.owner_name,
            source_url,
            snippet=snip,
            extractor="llm",
            confidence=CONFIDENCE,
            extra={"title": llm.owner_title, "provider": llm.provider},
        )
        filled.append("owner_name")
    return filled


async def extract(
    crawl: CrawlResult, company_id: str, name: str, batcher: LlmBatcher | None, current_year: int
) -> Extraction:
    pages = Pages.from_crawl(crawl)
    facts = run_all(pages, current_year)
    out = Extraction(facts=facts, pages=pages)
    owner = facts.get("owner_name")
    out.owner_title = str(owner.extra.get("title")) if owner and owner.extra.get("title") else None
    if batcher is None or not pages.pages:
        return out
    if "owner_name" in facts and "founded_year" in facts:
        return out
    text, url = llm_text(pages)
    llm = await batcher.submit(LlmRequest(id=company_id, name=name, text=text, source_url=url))
    if llm:
        out.llm_used = bool(merge_llm(facts, llm, url))
        out.services = llm.services or None
        if llm.owner_name and facts.get("owner_name") and facts["owner_name"].extractor == "llm":
            out.owner_title = llm.owner_title
    return out


def summarize_tech(facts: dict[str, Evidence]) -> list[str]:
    names: list[str] = []
    for cat in ("cms", "booking", "chat", "analytics", "legacy"):
        ev = facts.get(f"tech_{cat}")
        if ev is not None:
            names += [str(x) for x in ev.value]
    return names


def raw_facts(ex: Extraction) -> dict[str, Any]:
    """What we keep in companies.raw for the drawer (not scored)."""
    f = ex.facts
    ppl = f.get("people_named")
    return {
        "tech": summarize_tech(f),
        "people": ppl.extra.get("people", []) if ppl else [],
        "services": ex.services or [],
        "owner_title": ex.owner_title,
        "owner_source_url": f["owner_name"].source_url if "owner_name" in f else None,
        "email": f["email"].value if "email" in f else None,
        "street_address_site": f["street_address"].value if "street_address" in f else None,
    }
