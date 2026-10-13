"""Outbound HTTP plumbing shared by integrations and the crawler.

- `HostThrottle`: at most 1 request/second per host (crawl etiquette, Nominatim policy).
- `client()`: one httpx.AsyncClient factory with an honest User-Agent.
- SSRF guard: `assert_public_url` resolves the host and rejects private/loopback/link-local/
  metadata addresses and non-http(s) schemes. The crawler re-checks every redirect hop.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from urllib.parse import urlsplit

import httpx

from app.config import get_settings


class HostThrottle:
    def __init__(self, min_interval: float = 1.0) -> None:
        self.min_interval = min_interval
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}

    async def wait(self, host: str) -> None:
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            last = self._last.get(host)
            if last is not None:
                delay = self.min_interval - (time.monotonic() - last)
                if delay > 0:
                    await asyncio.sleep(delay)
            self._last[host] = time.monotonic()


# Process-wide throttle for third-party APIs (Nominatim, Overpass).
api_throttle = HostThrottle(1.0)


def default_headers() -> dict[str, str]:
    return {
        "User-Agent": get_settings().crawl_user_agent,
        "Accept-Language": "en-US,en;q=0.8",
    }


def client(**kwargs: object) -> httpx.AsyncClient:
    timeout = kwargs.pop("timeout", httpx.Timeout(10.0, connect=5.0))
    return httpx.AsyncClient(
        headers=default_headers(),
        timeout=timeout,  # type: ignore[arg-type]
        http2=True,
        follow_redirects=False,
        **kwargs,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------- SSRF guard


class BlockedURL(Exception):
    """Raised when a URL targets a non-public address or an unsupported scheme."""


_METADATA = {ipaddress.ip_address("169.254.169.254"), ipaddress.ip_address("fd00:ec2::254")}


def is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    if addr in _METADATA:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
        or (isinstance(addr, ipaddress.IPv4Address) and addr in ipaddress.ip_network("100.64.0.0/10"))
    )


async def resolve(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


async def assert_public_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise BlockedURL(f"scheme not allowed: {parts.scheme or '(none)'}")
    host = parts.hostname
    if not host:
        raise BlockedURL("missing host")
    if host.lower() in ("localhost", "localhost.localdomain") or host.lower().endswith(".localhost"):
        raise BlockedURL("localhost")
    # Literal IPs are checked directly; names are resolved and every address must be public.
    try:
        ipaddress.ip_address(host)
        addrs = [host]
    except ValueError:
        try:
            addrs = await resolve(host)
        except OSError as e:
            raise BlockedURL(f"dns failure: {e}") from e
    if not addrs:
        raise BlockedURL("no addresses")
    bad = [a for a in addrs if not is_public_ip(a)]
    if bad:
        raise BlockedURL(f"non-public address {bad[0]}")
