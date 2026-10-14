"""LLM gap-fill for owner name / founding year / services (prompts/extract.md).

- Called only for companies still missing owner_name or founded_year after the rules.
- Batched (up to 5 companies per call) by `LlmBatcher`, so a 60-company run is a handful of calls.
- Gemini first; on 429/5xx/timeout the same prompt goes to Groq; both down -> rules-only.
- Output is untrusted: `guard()` keeps a field only if it appears verbatim in `evidence_quote` and the
  quote is a substring of that company's input. Cached per company input for 30 days.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app import cache, configs
from app.config import get_settings
from app.net import HostThrottle

log = logging.getLogger(__name__)

MAX_CHARS = 6000
BATCH = 5
CONFIDENCE = 0.7

# Free-tier pacing: Gemini ~10 RPM, Groq 30 RPM.
_gemini_pace = HostThrottle(6.5)
_groq_pace = HostThrottle(2.1)

# Circuit breaker: after a provider fails, skip it for a while instead of paying its timeout per batch.
BREAKER_SECONDS = 300.0
_down_until: dict[str, float] = {}


def _available(provider: str) -> bool:
    return _down_until.get(provider, 0.0) <= time.monotonic()


def _trip(provider: str) -> None:
    _down_until[provider] = time.monotonic() + BREAKER_SECONDS


@dataclass
class LlmRequest:
    id: str
    name: str
    text: str
    source_url: str | None = None


@dataclass
class LlmFacts:
    id: str
    owner_name: str | None
    owner_title: str | None
    founded_year: int | None
    services: list[str] = field(default_factory=list)
    evidence_quote: str = ""
    provider: str = ""


class LlmUnavailable(Exception):
    pass


# ---------------------------------------------------------------- prompt


def system_prompt() -> str:
    """The system prompt + output schema from prompts/extract.md (everything before the user template)."""
    md = configs.extract_prompt()
    head = md.split("# User message template")[0]
    return head.replace("# System prompt — owner/founding extraction (batched)", "").strip()


def _sanitize(text: str) -> str:
    # Page text is data. Neutralise anything that could close our delimiter.
    return re.sub(r"</?\s*company", "‹company", text, flags=re.I)[:MAX_CHARS]


def user_prompt(items: list[LlmRequest], wrap_items: bool = False) -> str:
    blocks = [
        f'<company id="{r.id}" name="{_sanitize(r.name)[:120]}">\n{_sanitize(r.text)}\n</company>'
        for r in items
    ]
    tail = (
        '\n\nReturn a JSON object {"items": [...]} whose array follows the schema.'
        if wrap_items
        else "\n\nReturn the JSON array only."
    )
    return "\n".join(blocks) + tail


# ---------------------------------------------------------------- guard (pure)


def _norm(s: str) -> str:
    return " ".join(s.split()).lower()


def guard(obj: dict[str, Any], input_text: str, current_year: int | None = None) -> LlmFacts | None:
    """Apply the post-processing guard from extract.md. Returns None if the whole object is discarded."""
    year_now = current_year or datetime.now(UTC).year
    quote = obj.get("evidence_quote")
    if not isinstance(quote, str) or not quote.strip():
        return None
    q = _norm(quote)
    if q not in _norm(input_text):
        return None  # ungrounded quote: drop everything

    def grounded(v: Any) -> bool:
        return isinstance(v, str) and bool(v.strip()) and _norm(v) in q

    owner = obj.get("owner_name") if grounded(obj.get("owner_name")) else None
    title = obj.get("owner_title") if owner and grounded(obj.get("owner_title")) else None
    year_raw = obj.get("founded_year")
    year: int | None = None
    if isinstance(year_raw, int | str) and str(year_raw).isdigit():
        y = int(year_raw)
        if 1900 <= y <= year_now and str(y) in quote:
            year = y
    services = [s.strip() for s in obj.get("services") or [] if grounded(s)][:5]
    if owner is None and year is None and not services:
        return None
    return LlmFacts(
        id=str(obj.get("id", "")),
        owner_name=" ".join(owner.split()) if owner else None,
        owner_title=title,
        founded_year=year,
        services=services,
        evidence_quote=" ".join(quote.split()),
    )


def parse_output(raw: str) -> list[dict[str, Any]]:
    data = json.loads(raw)
    if isinstance(data, dict):
        data = data.get("items", data.get("companies", []))
    if not isinstance(data, list):
        raise ValueError("LLM output is not a JSON array")
    return [d for d in data if isinstance(d, dict)]


# ---------------------------------------------------------------- providers


async def _gemini(items: list[LlmRequest]) -> tuple[str, list[dict[str, Any]]]:
    from google import genai
    from google.genai import errors, types

    s = get_settings()
    if not s.gemini_api_key:
        raise LlmUnavailable("no gemini key")
    await _gemini_pace.wait("gemini")
    client = genai.Client(api_key=s.gemini_api_key)
    try:
        resp = await asyncio.wait_for(
            client.aio.models.generate_content(
                model=s.gemini_model,
                contents=user_prompt(items),
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt(), temperature=0, response_mime_type="application/json"
                ),
            ),
            timeout=15,  # flash answers in 2-5 s; a slow Gemini falls through to Groq quickly
        )
    except errors.APIError as e:
        raise LlmUnavailable(f"gemini {e.code}") from e
    except TimeoutError as e:
        raise LlmUnavailable("gemini timeout") from e
    return f"gemini:{s.gemini_model}", parse_output(resp.text or "[]")


async def _groq(items: list[LlmRequest]) -> tuple[str, list[dict[str, Any]]]:
    from groq import APIError, AsyncGroq

    s = get_settings()
    if not s.groq_api_key:
        raise LlmUnavailable("no groq key")
    await _groq_pace.wait("groq")
    client = AsyncGroq(api_key=s.groq_api_key, timeout=40)
    try:
        resp = await client.chat.completions.create(
            model=s.groq_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt()},
                {"role": "user", "content": user_prompt(items, wrap_items=True)},
            ],
        )
    except APIError as e:
        raise LlmUnavailable(f"groq {type(e).__name__}") from e
    return f"groq:{s.groq_model}", parse_output(resp.choices[0].message.content or "{}")


def _cache_key(item: LlmRequest) -> str:
    s = get_settings()
    return "llm:" + cache.sha256(f"{s.gemini_model}|{s.groq_model}|{system_prompt()}|{item.name}|{item.text}")


async def extract_batch(items: list[LlmRequest]) -> dict[str, LlmFacts | None]:
    """One provider call for up to 5 companies (cached per company). Never raises."""
    results: dict[str, LlmFacts | None] = {}
    todo: list[LlmRequest] = []
    for it in items:
        hit = await cache.get(_cache_key(it))
        if hit is not None:
            results[it.id] = guard({**hit["obj"], "id": it.id}, it.text) if hit.get("obj") else None
            if results[it.id]:
                results[it.id].provider = hit.get("provider", "cache")  # type: ignore[union-attr]
        else:
            todo.append(it)
    if not todo:
        return results

    raw: list[dict[str, Any]] = []
    provider = ""
    for name, call in (("gemini", _gemini), ("groq", _groq)):
        if not _available(name):
            continue
        try:
            provider, raw = await call(todo)
            break
        except (LlmUnavailable, ValueError, json.JSONDecodeError) as e:
            log.warning("LLM provider %s failed: %s", name, e)
            if "no " not in str(e):  # a missing key isn't an outage
                _trip(name)
            continue
    else:
        raise LlmUnavailable("all providers failed")

    by_id = {str(o.get("id")): o for o in raw}
    for it in todo:
        obj = by_id.get(it.id)
        await cache.set(_cache_key(it), {"obj": obj, "provider": provider}, cache.TTL["llm"])
        facts = guard({**obj, "id": it.id}, it.text) if obj else None
        if facts:
            facts.provider = provider
        results[it.id] = facts
    return results


# ---------------------------------------------------------------- batcher


class LlmBatcher:
    """Collects requests from concurrent per-company tasks; flushes at 5 or after `wait` seconds."""

    def __init__(self, size: int = BATCH, wait: float = 1.5) -> None:
        self.size = size
        self.wait = wait
        self.pending: list[tuple[LlmRequest, asyncio.Future[LlmFacts | None]]] = []
        self._timer: asyncio.Task[None] | None = None
        self.disabled = not get_settings().has_llm
        self.calls = 0
        self._inflight: set[asyncio.Task[None]] = set()

    async def submit(self, req: LlmRequest) -> LlmFacts | None:
        if self.disabled or not req.text.strip():
            return None
        fut: asyncio.Future[LlmFacts | None] = asyncio.get_running_loop().create_future()
        self.pending.append((req, fut))
        if len(self.pending) >= self.size:
            self._flush_now()
        elif self._timer is None:
            self._timer = asyncio.create_task(self._flush_later())
        return await fut

    async def _flush_later(self) -> None:
        await asyncio.sleep(self.wait)
        self._timer = None
        self._flush_now()

    def _flush_now(self) -> None:
        batch, self.pending = self.pending[: self.size], self.pending[self.size :]
        if self._timer is not None and not self.pending:
            self._timer.cancel()
            self._timer = None
        if batch:
            task = asyncio.create_task(self._run(batch))
            self._inflight.add(task)
            task.add_done_callback(self._inflight.discard)

    async def _run(self, batch: list[tuple[LlmRequest, asyncio.Future[LlmFacts | None]]]) -> None:
        try:
            out = await extract_batch([r for r, _ in batch])
            self.calls += 1  # successful answers only: "N LLM calls" in the UI must not count failures
        except Exception as e:
            log.warning("LLM disabled for the rest of this run: %s", e)
            self.disabled = True
            out = {}
        for req, fut in batch:
            if not fut.done():
                fut.set_result(out.get(req.id))

    async def drain(self) -> None:
        if self.pending:
            self._flush_now()
