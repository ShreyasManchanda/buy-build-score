"""Contact validation. Company-level only: syntax + MX for email (no SMTP RCPT probing, ever),
libphonenumber validity for phone. Website status/HTTPS/TLS comes from the crawler."""

from __future__ import annotations

import logging

import dns.asyncresolver
import dns.exception
import dns.resolver
from email_validator import EmailNotValidError, validate_email

from app import cache
from app.pipeline.dedup import phone_is_valid

log = logging.getLogger(__name__)

MX_TIMEOUT_S = 2.0


async def has_mx(domain: str) -> bool | None:
    """True/False when DNS answers; None when it couldn't be checked (timeout/servfail)."""
    key = f"mx:{domain.lower()}"
    hit = await cache.get(key)
    if hit is not None:
        return bool(hit["mx"])
    resolver = dns.asyncresolver.Resolver()
    resolver.lifetime = MX_TIMEOUT_S
    resolver.timeout = MX_TIMEOUT_S
    try:
        answer = await resolver.resolve(domain, "MX")
        ok = any(str(r.exchange).strip(".") for r in answer)  # a null MX ("." ) means no mail
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        ok = False
    except (dns.exception.Timeout, dns.resolver.NoNameservers, dns.exception.DNSException) as e:
        log.info("MX lookup for %s inconclusive: %s", domain, e)
        return None
    await cache.set(key, {"mx": ok}, cache.TTL["mx"])
    return ok


async def email_status(email: str | None) -> str:
    """'valid_mx' | 'no_mx' | 'invalid' | 'none'."""
    if not email:
        return "none"
    try:
        info = validate_email(email, check_deliverability=False)
    except EmailNotValidError:
        return "invalid"
    mx = await has_mx(info.domain)
    if mx is None:
        return "none"  # couldn't check; never claim validity we didn't verify
    return "valid_mx" if mx else "no_mx"


def phone_valid(e164: str | None) -> bool | None:
    return phone_is_valid(e164)
