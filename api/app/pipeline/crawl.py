"""Polite async crawler: homepage + up to 3 about/team/contact/careers pages per site.

Etiquette (all enforced here, not left to callers):
- robots.txt honoured (cached 24 h); a fully disallowed site is `blocked_robots` and never fetched.
- Honest User-Agent; 1 request/second per host; at most 4 pages per site.
- Only http(s); every hop (including redirects) passes the SSRF guard.
- Only text/html, max 3 MB per body; 25 s budget per domain.
- 2 retries with backoff (0.5 s, 1.5 s) on 429/5xx/timeouts, honouring Retry-After (capped).
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import ssl
import time
import zlib
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx
from selectolax.lexbor import LexborHTMLParser as HTMLParser

from app import cache, net
from app.config import get_settings
from app.pipeline.dedup import normalize_domain

log = logging.getLogger(__name__)

MAX_PAGES = 4
MAX_BYTES = 3 * 1024 * 1024
DOMAIN_BUDGET_S = 25.0
MAX_REDIRECTS = 5
RETRY_STATUS = {429, 500, 502, 503, 504}
BACKOFF = (0.5, 1.5)
ROBOTS_UA = "BuyBuildScoreBot"

# Page buckets, in priority order. One page per bucket, top 3 overall.
BUCKETS: list[tuple[str, re.Pattern[str]]] = [
    ("about", re.compile(r"about|our[-_ ]?story|history|who[-_ ]we[-_ ]are|company", re.I)),
    ("team", re.compile(r"team|staff|our[-_ ]people|leadership|meet[-_ ]", re.I)),
    ("contact", re.compile(r"contact", re.I)),
    ("careers", re.compile(r"careers?|jobs?|employment|hiring|join[-_ ]", re.I)),
]
_SKIP_EXT = re.compile(r"\.(pdf|jpe?g|png|gif|webp|svg|zip|docx?|xlsx?|mp4|mp3|css|js|xml|ics)$", re.I)


@dataclass
class Page:
    url: str
    final_url: str
    kind: str  # 'home' | 'about' | 'team' | 'contact' | 'careers'
    status: int
    html: str
    ttfb_ms: int
    bytes: int

    def to_cache(self) -> dict[str, Any]:
        d = asdict(self)
        d["html"] = _pack(self.html)
        return d

    @classmethod
    def from_cache(cls, d: dict[str, Any]) -> Page:
        return cls(**{**d, "html": _unpack(d["html"])})


@dataclass
class CrawlResult:
    domain: str | None
    status: str  # crawl_status
    start_url: str | None
    pages: list[Page] = field(default_factory=list)
    final_scheme: str | None = None
    tls_ok: bool | None = None
    ttfb_ms: int | None = None
    total_bytes: int = 0
    reachable: bool = False
    js_rendered: bool = False
    skipped_by_robots: list[str] = field(default_factory=list)
    error: str | None = None
    cached: bool = False

    @property
    def home(self) -> Page | None:
        return next((p for p in self.pages if p.kind == "home"), None)

    def to_cache(self) -> dict[str, Any]:
        d = asdict(self)
        d["pages"] = [p.to_cache() for p in self.pages]
        d.pop("cached")
        return d

    @classmethod
    def from_cache(cls, d: dict[str, Any]) -> CrawlResult:
        pages = [Page.from_cache(p) for p in d.get("pages", [])]
        return cls(**{**d, "pages": pages, "cached": True})


# ---------------------------------------------------------------- html storage


_STRIP = [
    re.compile(r"<style\b[^>]*>.*?</style>", re.S | re.I),
    re.compile(r"<svg\b[^>]*>.*?</svg>", re.S | re.I),
    re.compile(r"<!--(?!\[if).*?-->", re.S),
    re.compile(r"data:[a-z]+/[a-z0-9.+-]+;base64,[A-Za-z0-9+/=]{200,}", re.I),
]


def slim_html(html: str, limit: int = 400_000) -> str:
    """Drop bulk the extractors never read (CSS, inline SVG, comments, base64 blobs)."""
    for pat in _STRIP:
        html = pat.sub("", html)
    return html[:limit]


def _pack(html: str) -> str:
    return base64.b64encode(zlib.compress(html.encode("utf-8"), 6)).decode("ascii")


def _unpack(blob: str) -> str:
    return zlib.decompress(base64.b64decode(blob)).decode("utf-8")


# ---------------------------------------------------------------- page selection


def select_pages(home_html: str, base_url: str, limit: int = MAX_PAGES - 1) -> list[tuple[str, str]]:
    """Pick up to `limit` internal links, one per bucket (about > team > contact > careers)."""
    home_domain = normalize_domain(base_url)
    tree = HTMLParser(home_html)
    candidates: dict[str, list[tuple[int, str]]] = {b: [] for b, _ in BUCKETS}
    seen_paths: set[str] = {urlsplit(base_url).path.rstrip("/") or "/"}
    for a in tree.css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        url, _ = urldefrag(urljoin(base_url, href))
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or normalize_domain(url) != home_domain:
            continue
        path = parts.path.rstrip("/") or "/"
        if path in seen_paths or _SKIP_EXT.search(path):
            continue
        anchor = " ".join(a.text(separator=" ").split())[:80]
        for bucket, pat in BUCKETS:
            path_hit = bool(pat.search(path))
            if path_hit or pat.search(anchor):
                # Prefer path matches and shallow paths.
                score = (0 if path_hit else 10) + path.count("/")
                candidates[bucket].append((score, urlunsplit(parts._replace(query="", fragment=""))))
                seen_paths.add(path)
                break
    picked: list[tuple[str, str]] = []
    for bucket, _ in BUCKETS:
        if candidates[bucket] and len(picked) < limit:
            picked.append((bucket, min(candidates[bucket])[1]))
    return picked


def visible_text(html: str) -> str:
    tree = HTMLParser(html)
    for sel in ("script", "style", "noscript", "svg", "template", "iframe"):
        for n in tree.css(sel):
            n.decompose()
    body = tree.body or tree.root
    if body is None:
        return ""
    return " ".join(body.text(separator=" ").split())


def looks_js_rendered(html: str) -> bool:
    if len(visible_text(html)) >= 300:
        return False
    return bool(re.search(r"<div[^>]+id=[\"'](root|app|__next)[\"']", html, re.I))


# ---------------------------------------------------------------- robots


async def _robots(c: httpx.AsyncClient, throttle: net.HostThrottle, origin: str) -> RobotFileParser:
    key = f"robots:{urlsplit(origin).hostname}"

    async def fetch() -> dict[str, Any]:
        try:
            r = await _get(c, throttle, origin + "/robots.txt", accept_any=True)
        except (httpx.HTTPError, net.BlockedURL, ssl.SSLError) as e:
            return {"status": 0, "body": "", "error": type(e).__name__}
        return {"status": r.status_code, "body": r.text[:200_000] if r.status_code == 200 else ""}

    data = await cache.get_or_set(key, cache.TTL["robots"], fetch)
    rp = RobotFileParser()
    status = int(data.get("status", 0))
    if status in (401, 403) or status >= 500:
        rp.parse(["User-agent: *", "Disallow: /"])  # conservative: an erroring robots.txt means "don't"
    elif status == 200:
        rp.parse(data.get("body", "").splitlines())
    else:  # 404 / unreachable robots -> no restrictions published
        rp.parse([])
    return rp


# ---------------------------------------------------------------- fetching


@dataclass
class _Resp:
    url: str
    status_code: int
    headers: httpx.Headers
    text: str
    ttfb_ms: int
    nbytes: int


async def _get(
    c: httpx.AsyncClient, throttle: net.HostThrottle, url: str, accept_any: bool = False
) -> _Resp:
    """GET with manual redirects (SSRF-checked per hop), retries, size + type limits."""
    for _ in range(MAX_REDIRECTS + 1):
        await net.assert_public_url(url)
        resp = await _get_once(c, throttle, url, accept_any)
        if resp.status_code in (301, 302, 303, 307, 308) and "location" in resp.headers:
            url = urljoin(url, resp.headers["location"])
            continue
        return resp
    raise httpx.TooManyRedirects(f"more than {MAX_REDIRECTS} redirects")


async def _get_once(c: httpx.AsyncClient, throttle: net.HostThrottle, url: str, accept_any: bool) -> _Resp:
    host = urlsplit(url).hostname or ""
    for attempt in range(len(BACKOFF) + 1):
        await throttle.wait(host)
        t0 = time.monotonic()
        try:
            async with c.stream("GET", url) as r:
                ttfb = int((time.monotonic() - t0) * 1000)
                if r.status_code in RETRY_STATUS and attempt < len(BACKOFF):
                    await _sleep_retry(r.headers.get("retry-after"), BACKOFF[attempt])
                    continue
                ctype = r.headers.get("content-type", "")
                is_redirect = 300 <= r.status_code < 400
                if not accept_any and not is_redirect and "html" not in ctype.lower():
                    return _Resp(str(r.url), r.status_code, r.headers, "", ttfb, 0)
                chunks: list[bytes] = []
                size = 0
                async for chunk in r.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        break
                    chunks.append(chunk)
                body = b"".join(chunks)
                text = body.decode(r.encoding or "utf-8", errors="replace")
                return _Resp(str(r.url), r.status_code, r.headers, text, ttfb, size)
        except (httpx.TimeoutException, httpx.RemoteProtocolError):
            if attempt >= len(BACKOFF):
                raise
            await asyncio.sleep(BACKOFF[attempt])
    raise httpx.ConnectError("retries exhausted")  # pragma: no cover


async def _sleep_retry(retry_after: str | None, default: float) -> None:
    delay = default
    if retry_after and retry_after.strip().isdigit():
        delay = min(float(retry_after.strip()), 5.0)
    await asyncio.sleep(delay)


def _is_tls_error(e: BaseException) -> bool:
    seen: set[int] = set()
    cur: BaseException | None = e
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, ssl.SSLError) or "CERTIFICATE" in str(cur).upper():
            return True
        cur = cur.__cause__ or cur.__context__
    return False


# ---------------------------------------------------------------- crawler


class Crawler:
    """One per run: shares the client, the global semaphore and the per-host throttle."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        concurrency: int | None = None,
        per_host_interval: float = 1.0,
    ) -> None:
        self._own_client = client is None
        self.client = client or net.client(timeout=httpx.Timeout(10.0, connect=5.0))
        self.sem = asyncio.Semaphore(concurrency or get_settings().crawl_concurrency)
        self.throttle = net.HostThrottle(per_host_interval)

    async def __aenter__(self) -> Crawler:
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._own_client:
            await self.client.aclose()

    async def crawl(self, website: str | None, use_cache: bool = True) -> CrawlResult:
        domain = normalize_domain(website)
        if not website or not domain:
            return CrawlResult(domain=None, status="no_site", start_url=None)
        key = f"crawl:{domain}"
        if use_cache:
            hit = await cache.get(key)
            if hit:
                return CrawlResult.from_cache(hit)
        async with self.sem:
            try:
                result = await asyncio.wait_for(self._crawl(website, domain), DOMAIN_BUDGET_S)
            except TimeoutError:
                result = CrawlResult(domain=domain, status="unreachable", start_url=website, error="timeout")
        if result.status in ("ok", "partial", "blocked_robots"):
            await cache.set(key, result.to_cache(), cache.TTL["crawl"])
        return result

    async def _crawl(self, website: str, domain: str) -> CrawlResult:
        start = website if re.match(r"^https?://", website, re.I) else f"http://{website}"
        result = CrawlResult(domain=domain, status="unreachable", start_url=start)
        origin = "{0.scheme}://{0.netloc}".format(urlsplit(start))
        try:
            await net.assert_public_url(start)
        except net.BlockedURL as e:
            result.error = f"blocked: {e}"
            return result

        robots = await _robots(self.client, self.throttle, origin)
        if not robots.can_fetch(ROBOTS_UA, start):
            result.status = "blocked_robots"
            result.reachable = True
            result.error = "robots.txt disallows this site"
            return result

        home, tls_ok = await self._fetch_home(start)
        result.tls_ok = tls_ok
        if home is None or home.status_code >= 400 or not home.text:
            result.error = f"homepage HTTP {home.status_code}" if home else "homepage unreachable"
            return result
        result.reachable = True
        result.final_scheme = urlsplit(home.url).scheme
        result.ttfb_ms = home.ttfb_ms
        result.pages.append(
            Page(start, home.url, "home", home.status_code, slim_html(home.text), home.ttfb_ms, home.nbytes)
        )
        result.js_rendered = looks_js_rendered(home.text)

        failures = 0
        for kind, url in select_pages(home.text, home.url):
            if not robots.can_fetch(ROBOTS_UA, url):
                result.skipped_by_robots.append(url)
                continue
            try:
                r = await _get(self.client, self.throttle, url)
            except (httpx.HTTPError, net.BlockedURL, ssl.SSLError) as e:
                log.info("subpage %s failed: %s", url, e)
                failures += 1
                continue
            if r.status_code >= 400 or not r.text:
                failures += 1
                continue
            result.pages.append(Page(url, r.url, kind, r.status_code, slim_html(r.text), r.ttfb_ms, r.nbytes))

        result.total_bytes = sum(p.bytes for p in result.pages)
        result.status = "partial" if failures or result.skipped_by_robots else "ok"
        return result

    async def _fetch_home(self, start: str) -> tuple[_Resp | None, bool | None]:
        """Fetch the homepage; if HTTPS fails on a bad certificate, fall back to plain HTTP."""
        tls_ok: bool | None = None
        try:
            r = await _get(self.client, self.throttle, start)
            if urlsplit(r.url).scheme == "https":
                tls_ok = True
            return r, tls_ok
        except (httpx.HTTPError, ssl.SSLError) as e:
            if urlsplit(start).scheme == "https" and _is_tls_error(e):
                http_url = "http://" + start.split("://", 1)[1]
                try:
                    return await _get(self.client, self.throttle, http_url), False
                except (httpx.HTTPError, net.BlockedURL, ssl.SSLError):
                    return None, False
            log.info("homepage %s failed: %s", start, e)
            return None, tls_ok
        except net.BlockedURL:
            return None, None
