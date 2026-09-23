"""Client IP resolution, hashing, and allowlist matching for rate limiting.

See docs/developer/rate-limiting-plan.md §7-§8. Two proxies sit in front of
``apps/api`` in production (nginx, then the Next.js rewrite proxy) — the hop
count must be measured against the real deployment, not assumed. Getting it
wrong does not degrade gracefully: every per-IP limit collapses to a single
global counter shared by every client, i.e. a self-inflicted outage.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
from functools import lru_cache
from ipaddress import IPv4Network, IPv6Network

from fastapi import Request

from app.config import settings

logger = logging.getLogger(__name__)

_IPNetwork = IPv4Network | IPv6Network


def _fallback_subject(request: Request) -> str:
    client = request.client
    return client.host if client else "unknown"


def resolve_client_ip(request: Request) -> str:
    """Return the normalised client IP (v6 collapsed to its /64) for this request.

    Never raw beyond this module — callers should immediately pass the result
    to :func:`hash_subject` before using it as a Redis key or log field.
    """
    if not settings.TRUST_PROXY_HEADERS:
        return _normalise(_fallback_subject(request))

    forwarded_for = request.headers.get("X-Forwarded-For")
    if not forwarded_for:
        return _normalise(_fallback_subject(request))

    hops = [h.strip() for h in forwarded_for.split(",") if h.strip()]
    if not hops:
        return _normalise(_fallback_subject(request))

    # Never the leftmost entry — it is attacker-supplied. nginx appends via
    # $proxy_add_x_forwarded_for, so the real client sits at the right-hand
    # end, `TRUSTED_PROXY_HOPS` entries in from the end.
    hops_back = max(1, settings.TRUSTED_PROXY_HOPS)
    if hops_back > len(hops):
        # The chain is shorter than configured — either the hop count is wrong
        # or a proxy dropped the header. Fall back to the rightmost entry (the
        # nearest trusted proxy appended it), never to hops[0], which the
        # client can set freely and which would hand out a per-IP bypass.
        logger.warning(
            "rate_limit.xff_short_chain hops=%s configured=%s — resolved "
            "subject may be a proxy, not the client (see plan §7)",
            len(hops),
            settings.TRUSTED_PROXY_HOPS,
        )
        return _normalise(hops[-1])
    return _normalise(hops[-hops_back])


def _normalise(raw_ip: str) -> str:
    """Strip a port suffix if present and collapse IPv6 to its /64 prefix."""
    raw_ip = raw_ip.strip()
    try:
        addr = ipaddress.ip_address(raw_ip)
    except ValueError:
        # Host:port form, e.g. from request.client.host in some ASGI servers.
        if ":" in raw_ip and raw_ip.count(":") == 1:
            raw_ip = raw_ip.rsplit(":", 1)[0]
        try:
            addr = ipaddress.ip_address(raw_ip)
        except ValueError:
            return raw_ip
    if addr.version == 6:
        network = ipaddress.ip_network(f"{addr}/64", strict=False)
        return str(network.network_address)
    return str(addr)


def hash_subject(normalised_ip: str) -> str:
    """Hash a normalised IP for storage. Redis and logs never hold a raw IP."""
    salted = f"{settings.RATE_LIMIT_IP_SALT}{normalised_ip}".encode("utf-8")
    return hashlib.sha256(salted).hexdigest()[:16]


def resolve_and_hash(request: Request) -> str:
    """Convenience: resolve then hash in one call."""
    return hash_subject(resolve_client_ip(request))


@lru_cache(maxsize=1)
def _parsed_allowlist(raw: str) -> tuple[_IPNetwork, ...]:
    networks: list[_IPNetwork] = []
    for entry in (e.strip() for e in raw.split(",")):
        if not entry:
            continue
        # Malformed entries are rejected at settings load (Settings validator);
        # this is a defensive re-parse, not the primary validation point.
        networks.append(ipaddress.ip_network(entry, strict=False))
    return tuple(networks)


def _allowlist_networks() -> tuple[_IPNetwork, ...]:
    return _parsed_allowlist(settings.RATE_LIMIT_IP_ALLOWLIST)


def ip_in_allowlist(normalised_ip: str) -> bool:
    """Linear scan — sub-microsecond for an allowlist of this size."""
    try:
        addr = ipaddress.ip_address(normalised_ip)
    except ValueError:
        return False
    return any(addr in network for network in _allowlist_networks())


# Synthetic subject for the runtime's service JWT (see app/routers/users.py
# BOT_SERVICE_EMAIL). Exempting this identity from per-IP concurrency is
# justified because all internal traffic originates from one container
# address — it must NEVER exempt org-scoped limits (org concurrency, org
# daily quota), which are the actual budget being protected and have nothing
# to do with who submitted the request. See rate-limiting-plan.md §8b.
INTERNAL_SERVICE_SUBJECT = "bot@voicera.internal"


def is_internal_service_subject(email: str | None) -> bool:
    return email == INTERNAL_SERVICE_SUBJECT
