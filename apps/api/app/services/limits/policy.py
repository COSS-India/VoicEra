"""Effective-limit resolution: per-org override → env default.

A single 60-second in-process TTL cache, mirroring the existing
``get_org_concurrent_limit`` pattern (``campaign_repository.py``) — which this
module now delegates to, so there is one resolver and one cache rather than
two that can drift apart. A per-worker cache is fine here: limits change
rarely and a minute of skew is harmless.

Reads go through ``run_in_threadpool`` because the underlying lookup is a
synchronous pymongo call and ``apps/api`` runs as a single uvicorn worker
(no ``--workers``) — a blocking round trip here would stall every other
in-flight request on the event loop.
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Any

from fastapi.concurrency import run_in_threadpool

from app.config import settings

logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 60
_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}

# Concurrency cap for exempt orgs: never binds in practice, and stays an
# exact integer inside the Redis Lua slot script (which works in doubles).
UNLIMITED_CONCURRENCY = 1_000_000


@lru_cache(maxsize=4)
def _parse_csv(raw: str) -> frozenset[str]:
    return frozenset(v.strip() for v in raw.split(",") if v.strip())


def is_rate_limit_exempt(*, org_id: str | None = None, email: str | None = None) -> bool:
    """True when ``org_id`` or ``email`` is listed in the exemption settings.

    Matching is exact, never case-folded: Users are looked up by exact email,
    so ``Automation@x`` is a different (and freely registrable) account from
    ``automation@x`` and must not inherit its exemption.

    Keyed on the raw setting string, so the parse happens once per distinct
    value rather than per call.
    """
    if org_id and org_id in _parse_csv(settings.RATE_LIMIT_EXEMPT_ORG_IDS):
        return True
    return bool(email and email in _parse_csv(settings.RATE_LIMIT_EXEMPT_EMAILS))


def _cached_org_lookup(org_id: str) -> dict[str, Any] | None:
    from app.services.org_service import get_organisation

    return get_organisation(org_id)


async def _get_org(org_id: str) -> dict[str, Any] | None:
    now = time.monotonic()
    cached = _cache.get(org_id)
    if cached and now - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]
    org = await run_in_threadpool(_cached_org_lookup, org_id)
    _cache[org_id] = (now, org)
    return org


def invalidate_org_cache(org_id: str | None = None) -> None:
    """Drop cached policy for one org, or all orgs when called with no argument."""
    if org_id is None:
        _cache.clear()
    else:
        _cache.pop(org_id, None)


async def get_org_concurrency_limit(org_id: str) -> int:
    """Effective max concurrent calls for ``org_id``.

    Delegates to the same field the existing campaign dispatcher reads
    (``concurrent_call_limit``) so both call paths agree on one number.
    """
    if is_rate_limit_exempt(org_id=org_id):
        return UNLIMITED_CONCURRENCY
    org = await _get_org(org_id)
    if org and org.get("concurrent_call_limit") is not None:
        try:
            return max(1, int(org["concurrent_call_limit"]))
        except (TypeError, ValueError):
            pass
    return settings.DEFAULT_ORG_CONCURRENCY_LIMIT


async def get_org_daily_call_seconds(org_id: str) -> int:
    """Effective daily call-seconds quota for ``org_id``."""
    org = await _get_org(org_id)
    if org and org.get("daily_call_seconds") is not None:
        try:
            return max(0, int(org["daily_call_seconds"]))
        except (TypeError, ValueError):
            pass
    return settings.ORG_DAILY_CALL_SECONDS


async def get_org_max_call_duration_seconds(
    org_id: str, agent_call_timeout_seconds: float | None = None
) -> int:
    """Effective single-call duration cap for ``org_id``.

    Precedence: agent's own ``call_timeout_seconds`` (if set), else the org
    override, else the env default — all clamped by
    ``MAX_CALL_DURATION_CEILING_SECONDS``, which is an unconditional safety
    rail an org cannot raise by editing its own config (rate-limiting-plan.md
    §8c).
    """
    ceiling = settings.MAX_CALL_DURATION_CEILING_SECONDS
    if agent_call_timeout_seconds:
        return min(int(agent_call_timeout_seconds), ceiling)

    org = await _get_org(org_id)
    if org and org.get("max_call_duration_seconds") is not None:
        try:
            return min(int(org["max_call_duration_seconds"]), ceiling)
        except (TypeError, ValueError):
            pass
    return min(settings.MAX_CALL_DURATION_SECONDS, ceiling)
