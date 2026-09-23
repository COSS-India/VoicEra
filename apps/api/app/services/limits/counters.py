"""Redis-backed fixed-window counters and usage accumulators.

Separate from ``app.services.call_concurrency.rate_limiter`` (which owns
concurrency slots and the sliding-window token bucket) — this module owns the
simpler fixed-window primitives added for signup/auth/reset/usage limits. Both
share the same Redis instance via ``REDIS_URL``; each keeps its own lazily
constructed client to avoid coupling the two packages.

Every key here carries a TTL. No cleanup job, no unbounded growth.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time

import redis as sync_redis
import redis.asyncio as aioredis
from redis.exceptions import NoScriptError

from app.config import settings

logger = logging.getLogger(__name__)

_INCR_WINDOW_SCRIPT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local count = redis.call('INCR', key)
if count == 1 then
    redis.call('EXPIRE', key, ttl)
end
local remaining_ttl = redis.call('TTL', key)
if remaining_ttl < 0 then
    remaining_ttl = ttl
end
return {count, remaining_ttl}
"""

_CLAIM_ONCE_SCRIPT = """
local key = KEYS[1]
local ttl = tonumber(ARGV[1])
return redis.call('SET', key, 1, 'NX', 'EX', ttl) and 1 or 0
"""


class _Counters:
    def __init__(self) -> None:
        self._client: aioredis.Redis | None = None
        self._lock = asyncio.Lock()
        self._incr_sha: str | None = None
        self._claim_sha: str | None = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._client is None:
            async with self._lock:
                if self._client is None:
                    self._client = await aioredis.from_url(
                        settings.REDIS_URL, decode_responses=True
                    )
        return self._client

    async def _eval(self, script: str, sha_attr: str, keys: list[str], args: list) -> object:
        redis_client = await self._get_redis()
        sha = getattr(self, sha_attr)
        if sha is None:
            sha = await redis_client.script_load(script)
            setattr(self, sha_attr, sha)
        try:
            return await redis_client.evalsha(sha, len(keys), *keys, *args)
        except NoScriptError:
            # Only retry when the server has genuinely forgotten the script
            # (restart, SCRIPT FLUSH). Retrying on any exception would re-run
            # a script that may already have applied — INCR is not idempotent,
            # so a timeout on the reply would silently double-count.
            setattr(self, sha_attr, None)
            return await redis_client.eval(script, len(keys), *keys, *args)

    async def incr_window(self, key: str, limit: int, ttl: int) -> tuple[bool, int, int]:
        """Atomically increment ``key``, expiring it ``ttl`` seconds after first use.

        Returns ``(allowed, count, retry_after)``. ``retry_after`` is the
        window's remaining TTL, suitable for a ``Retry-After`` header.
        """
        count, remaining_ttl = await self._eval(
            _INCR_WINDOW_SCRIPT, "_incr_sha", [key], [limit, ttl]
        )
        count = int(count)
        remaining_ttl = int(remaining_ttl)
        return count <= limit, count, remaining_ttl

    async def claim_once(self, key: str, ttl: int) -> bool:
        """``SET NX`` — true the first time ``key`` is claimed, false on replay.

        Used by Layer 2b to make a WebSocket admission token's nonce
        single-use: without this check a valid signed token is replayable for
        its whole lifetime.
        """
        result = await self._eval(_CLAIM_ONCE_SCRIPT, "_claim_sha", [key], [ttl])
        return bool(int(result))

    async def add_usage(self, key: str, amount: float, ttl: int) -> float:
        """``INCRBYFLOAT`` a usage accumulator, expiring it if newly created."""
        redis_client = await self._get_redis()
        pipe = redis_client.pipeline()
        pipe.incrbyfloat(key, amount)
        pipe.expire(key, ttl, nx=True)
        results = await pipe.execute()
        return float(results[0])

    async def get_usage(self, key: str) -> float:
        redis_client = await self._get_redis()
        value = await redis_client.get(key)
        return float(value) if value is not None else 0.0


counters = _Counters()


def utc_day_key() -> str:
    """UTC calendar day as YYYYMMDD, so daily counters don't reset twice or
    skip a day across a DST change (there is no DST in UTC)."""
    return time.strftime("%Y%m%d", time.gmtime())


# Org daily call-seconds usage key, shared between the writer below (Layer 4,
# called from the synchronous call_log_service.patch_call_log) and the
# reader in call_admission.py (Layer 2) — one key format, one place it's
# defined, so the two can't drift apart.
_USAGE_TTL_SECONDS = 48 * 3600


def usage_key(org_id: str) -> str:
    return f"usage:dur:{org_id}:{utc_day_key()}"


_sync_client: sync_redis.Redis | None = None
_sync_client_lock = threading.Lock()


def _get_sync_redis() -> sync_redis.Redis:
    global _sync_client
    if _sync_client is None:
        with _sync_client_lock:
            if _sync_client is None:
                _sync_client = sync_redis.Redis.from_url(
                    settings.REDIS_URL, decode_responses=True
                )
    return _sync_client


def add_usage_sync(org_id: str, amount: float, ttl: int = _USAGE_TTL_SECONDS) -> None:
    """Synchronous org daily usage increment.

    ``call_log_service.patch_call_log`` (the only caller) is itself
    synchronous pymongo code, so this uses a small blocking Redis client
    rather than pulling the whole call-finalisation path onto the event
    loop. Never raises — a Redis failure here must not break call
    finalisation (rate-limiting-plan.md §9, Layer 4).
    """
    try:
        client = _get_sync_redis()
        key = usage_key(org_id)
        pipe = client.pipeline()
        pipe.incrbyfloat(key, amount)
        pipe.expire(key, ttl, nx=True)
        pipe.execute()
    except Exception as exc:
        logger.error(
            "rate_limit.fail_open scope=usage_increment org_id=%s error=%s",
            org_id,
            exc,
        )
