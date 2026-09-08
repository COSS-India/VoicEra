"""Campaign circuit breaker using Redis sliding windows."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import redis.asyncio as aioredis

from app.config import settings
from app.constants.campaign import DEFAULT_CIRCUIT_BREAKER_CONFIG
from app.services.campaign import campaign_repository as repo
from app.services.campaign.campaign_event_publisher import get_campaign_event_publisher

logger = logging.getLogger(__name__)

MAX_RECENT_FAILURES = 20


class CircuitBreaker:
    def __init__(self) -> None:
        self.redis_client: aioredis.Redis | None = None

    async def _get_redis(self) -> aioredis.Redis:
        if self.redis_client is None:
            self.redis_client = await aioredis.from_url(
                settings.REDIS_URL, decode_responses=True
            )
        return self.redis_client

    @staticmethod
    def _keys(campaign_id: str) -> tuple[str, str]:
        return f"cb_failures:{campaign_id}", f"cb_successes:{campaign_id}"

    @staticmethod
    def _recent_failures_key(campaign_id: str) -> str:
        return f"cb_recent_failures:{campaign_id}"

    async def _push_recent_failure(
        self, campaign_id: str, call_id: str, reason: str | None
    ) -> None:
        redis_client = await self._get_redis()
        key = self._recent_failures_key(campaign_id)
        entry = json.dumps({"call_id": call_id, "reason": reason, "ts": time.time()})
        await redis_client.lpush(key, entry)
        await redis_client.ltrim(key, 0, MAX_RECENT_FAILURES - 1)
        await redis_client.expire(
            key, DEFAULT_CIRCUIT_BREAKER_CONFIG["window_seconds"] + 60
        )

    async def record_call_outcome(
        self,
        campaign_id: str,
        is_failure: bool,
        config: dict[str, Any] | None = None,
    ) -> tuple[bool, dict[str, Any] | None]:
        cb_config = {**DEFAULT_CIRCUIT_BREAKER_CONFIG, **(config or {})}
        if not cb_config.get("enabled", True):
            return False, None
        redis_client = await self._get_redis()
        window_seconds = int(cb_config["window_seconds"])
        threshold = float(cb_config["failure_threshold"])
        min_calls = int(cb_config["min_calls_in_window"])
        now = time.time()
        window_start = now - window_seconds
        fail_key, succ_key = self._keys(campaign_id)
        lua_script = """
        local fail_key = KEYS[1]
        local succ_key = KEYS[2]
        local now = tonumber(ARGV[1])
        local window_start = tonumber(ARGV[2])
        local is_failure = tonumber(ARGV[3])
        local threshold = tonumber(ARGV[4])
        local min_calls = tonumber(ARGV[5])
        local ttl = tonumber(ARGV[6])
        redis.call('ZREMRANGEBYSCORE', fail_key, 0, window_start)
        redis.call('ZREMRANGEBYSCORE', succ_key, 0, window_start)
        if is_failure == 1 then
            redis.call('ZADD', fail_key, now, now)
        else
            redis.call('ZADD', succ_key, now, now)
        end
        redis.call('EXPIRE', fail_key, ttl)
        redis.call('EXPIRE', succ_key, ttl)
        local failures = redis.call('ZCARD', fail_key)
        local successes = redis.call('ZCARD', succ_key)
        local total = failures + successes
        if total >= min_calls and (failures / total) >= threshold then
            return {1, failures, successes, total}
        end
        return {0, failures, successes, total}
        """
        result = await redis_client.eval(
            lua_script,
            2,
            fail_key,
            succ_key,
            now,
            window_start,
            1 if is_failure else 0,
            threshold,
            min_calls,
            window_seconds + 60,
        )
        tripped = bool(result[0])
        failure_count = int(result[1])
        success_count = int(result[2])
        total = int(result[3])
        failure_rate = failure_count / total if total > 0 else 0.0
        stats = {
            "failure_rate": failure_rate,
            "failure_count": failure_count,
            "success_count": success_count,
            "threshold": threshold,
            "window_seconds": window_seconds,
        }
        return tripped, stats

    async def is_circuit_open(
        self, campaign_id: str, config: dict[str, Any] | None = None
    ) -> tuple[bool, dict[str, Any] | None]:
        cb_config = {**DEFAULT_CIRCUIT_BREAKER_CONFIG, **(config or {})}
        if not cb_config.get("enabled", True):
            return False, None
        redis_client = await self._get_redis()
        window_seconds = int(cb_config["window_seconds"])
        threshold = float(cb_config["failure_threshold"])
        min_calls = int(cb_config["min_calls_in_window"])
        now = time.time()
        window_start = now - window_seconds
        fail_key, succ_key = self._keys(campaign_id)
        lua_script = """
        local fail_key = KEYS[1]
        local succ_key = KEYS[2]
        local window_start = tonumber(ARGV[1])
        local threshold = tonumber(ARGV[2])
        local min_calls = tonumber(ARGV[3])
        redis.call('ZREMRANGEBYSCORE', fail_key, 0, window_start)
        redis.call('ZREMRANGEBYSCORE', succ_key, 0, window_start)
        local failures = redis.call('ZCARD', fail_key)
        local successes = redis.call('ZCARD', succ_key)
        local total = failures + successes
        if total >= min_calls and (failures / total) >= threshold then
            return {1, failures, successes, total}
        end
        return {0, failures, successes, total}
        """
        result = await redis_client.eval(
            lua_script,
            2,
            fail_key,
            succ_key,
            window_start,
            threshold,
            min_calls,
        )
        is_open = bool(result[0])
        failure_count = int(result[1])
        success_count = int(result[2])
        total = int(result[3])
        failure_rate = failure_count / total if total > 0 else 0.0
        stats = {
            "failure_rate": failure_rate,
            "failure_count": failure_count,
            "success_count": success_count,
            "threshold": threshold,
            "window_seconds": window_seconds,
        }
        return is_open, stats

    async def record_and_evaluate(
        self,
        campaign_id: str,
        is_failure: bool,
        *,
        call_id: str | None = None,
        reason: str | None = None,
    ) -> None:
        try:
            campaign = repo.get_campaign_by_id(campaign_id)
            if not campaign or campaign.get("state") != "running":
                return
            metadata = campaign.get("orchestrator_metadata") or {}
            cb_config = metadata.get("circuit_breaker") or {}
            if is_failure and call_id:
                await self._push_recent_failure(campaign_id, call_id, reason)
            tripped, stats = await self.record_call_outcome(
                campaign_id, is_failure, config=cb_config
            )
            if tripped and stats:
                repo.update_campaign(campaign_id, state="paused")
                repo.append_campaign_log(
                    campaign_id,
                    level="warning",
                    event="circuit_breaker_tripped",
                    message=(
                        f"Paused: failure rate {stats['failure_rate']:.2%} "
                        f"exceeded threshold {stats['threshold']:.2%}"
                    ),
                    details=stats,
                )
                publisher = await get_campaign_event_publisher()
                await publisher.publish_circuit_breaker_tripped(
                    campaign_id=campaign_id,
                    failure_rate=stats["failure_rate"],
                    failure_count=stats["failure_count"],
                    success_count=stats["success_count"],
                    threshold=stats["threshold"],
                    window_seconds=stats["window_seconds"],
                )
        except Exception as exc:
            logger.error("Circuit breaker error campaign=%s: %s", campaign_id, exc)

    async def reset(self, campaign_id: str) -> bool:
        redis_client = await self._get_redis()
        fail_key, succ_key = self._keys(campaign_id)
        recent_key = self._recent_failures_key(campaign_id)
        await redis_client.delete(fail_key, succ_key, recent_key)
        return True


circuit_breaker = CircuitBreaker()
