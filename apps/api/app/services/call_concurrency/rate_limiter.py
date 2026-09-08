"""Concurrent call limiting and rate limiting via Redis."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Optional

import redis.asyncio as aioredis

from app.config import settings

FLEET_CONCURRENT_KEY = "concurrent_calls_fleet"


@dataclass(frozen=True)
class ConcurrentSlotAcquisition:
    slot_id: str
    active_count: int


class RateLimiter:
    def __init__(self) -> None:
        self.redis_client: aioredis.Redis | None = None
        self.stale_call_timeout = 1200

    async def _get_redis(self) -> aioredis.Redis:
        if self.redis_client is None:
            self.redis_client = await aioredis.from_url(
                settings.REDIS_URL, decode_responses=True
            )
        return self.redis_client

    async def acquire_token(
        self,
        organization_id: str,
        rate_limit: int = 1,
        *,
        scope_key: str | None = None,
    ) -> bool:
        redis_client = await self._get_redis()
        key = f"rate_limit:{scope_key or organization_id}"
        now = time.time()
        window_start = now - 1.0
        lua_script = """
        local key = KEYS[1]
        local now = tonumber(ARGV[1])
        local window_start = tonumber(ARGV[2])
        local max_requests = tonumber(ARGV[3])
        redis.call('ZREMRANGEBYSCORE', key, 0, window_start)
        local current_requests = redis.call('ZCARD', key)
        if current_requests < max_requests then
            redis.call('ZADD', key, now, now)
            redis.call('EXPIRE', key, 2)
            return 1
        else
            return 0
        end
        """
        result = await redis_client.eval(
            lua_script, 1, key, now, window_start, rate_limit
        )
        return bool(result)

    async def try_acquire_concurrent_slot_details(
        self,
        organization_id: str,
        max_concurrent: int = 20,
        *,
        scope_key: str | None = None,
        scope_max_concurrent: int | None = None,
    ) -> ConcurrentSlotAcquisition | None:
        redis_client = await self._get_redis()
        concurrent_key = f"concurrent_calls:{organization_id}"
        scope_concurrent_key = f"concurrent_calls:{scope_key}" if scope_key else ""
        now = time.time()
        stale_cutoff = now - self.stale_call_timeout
        slot_id = f"{int(now * 1000)}_{uuid.uuid4().hex[:8]}"
        lua_script = """
        local key = KEYS[1]
        local scope_key = KEYS[2]
        local fleet_key = KEYS[3]
        local now = tonumber(ARGV[1])
        local max_concurrent = tonumber(ARGV[2])
        local stale_cutoff = tonumber(ARGV[3])
        local slot_id = ARGV[4]
        local scope_max_concurrent = tonumber(ARGV[5])
        local fleet_member = ARGV[6]
        redis.call('ZREMRANGEBYSCORE', key, 0, stale_cutoff)
        local current_count = redis.call('ZCARD', key)
        if current_count >= max_concurrent then
            return nil
        end
        if scope_key ~= '' then
            redis.call('ZREMRANGEBYSCORE', scope_key, 0, stale_cutoff)
            if redis.call('ZCARD', scope_key) >= scope_max_concurrent then
                return nil
            end
            redis.call('ZADD', scope_key, now, slot_id)
            redis.call('EXPIRE', scope_key, 3600)
        end
        redis.call('ZADD', key, now, slot_id)
        redis.call('EXPIRE', key, 3600)
        redis.call('ZREMRANGEBYSCORE', fleet_key, 0, stale_cutoff)
        redis.call('ZADD', fleet_key, now, fleet_member)
        redis.call('EXPIRE', fleet_key, 3600)
        return {slot_id, current_count + 1}
        """
        result = await redis_client.eval(
            lua_script,
            3,
            concurrent_key,
            scope_concurrent_key,
            FLEET_CONCURRENT_KEY,
            now,
            max_concurrent,
            stale_cutoff,
            slot_id,
            scope_max_concurrent if scope_max_concurrent is not None else 0,
            f"{organization_id}:{slot_id}",
        )
        if not result:
            return None
        acquired_slot_id, active_count = result
        return ConcurrentSlotAcquisition(
            slot_id=str(acquired_slot_id),
            active_count=int(active_count),
        )

    async def release_concurrent_slot(
        self,
        organization_id: str,
        slot_id: str,
        scope_key: str | None = None,
    ) -> bool | None:
        if not slot_id:
            return False
        redis_client = await self._get_redis()
        concurrent_key = f"concurrent_calls:{organization_id}"
        try:
            removed = await redis_client.zrem(concurrent_key, slot_id)
            await redis_client.zrem(FLEET_CONCURRENT_KEY, f"{organization_id}:{slot_id}")
            if scope_key:
                await redis_client.zrem(f"concurrent_calls:{scope_key}", slot_id)
            return bool(removed)
        except Exception:
            return None

    @staticmethod
    def _from_number_pool_key(organization_id: str, pool_scope: str) -> str:
        return f"from_number_pool:{organization_id}:{pool_scope}"

    async def initialize_from_number_pool(
        self,
        organization_id: str,
        from_numbers: list[str],
        pool_scope: str,
    ) -> bool:
        if not from_numbers:
            return False
        redis_client = await self._get_redis()
        key = self._from_number_pool_key(organization_id, pool_scope)
        members = {number: 0 for number in from_numbers}
        await redis_client.zadd(key, members, nx=True)
        await redis_client.expire(key, 3600)
        return True

    async def acquire_from_number(
        self, organization_id: str, pool_scope: str
    ) -> str | None:
        redis_client = await self._get_redis()
        key = self._from_number_pool_key(organization_id, pool_scope)
        now = time.time()
        stale_cutoff = now - self.stale_call_timeout
        lua_script = """
        local key = KEYS[1]
        local now = tonumber(ARGV[1])
        local stale_cutoff = tonumber(ARGV[2])
        local stale = redis.call('ZRANGEBYSCORE', key, 1, stale_cutoff)
        for i, member in ipairs(stale) do
            redis.call('ZADD', key, 0, member)
        end
        local available = redis.call('ZRANGEBYSCORE', key, 0, 0)
        if #available == 0 then
            return nil
        end
        local idx = math.random(#available)
        local chosen = available[idx]
        redis.call('ZADD', key, now, chosen)
        return chosen
        """
        return await redis_client.eval(lua_script, 1, key, now, stale_cutoff)

    async def release_from_number(
        self, organization_id: str, from_number: str, pool_scope: str
    ) -> bool:
        if not from_number:
            return False
        redis_client = await self._get_redis()
        key = self._from_number_pool_key(organization_id, pool_scope)
        lua_script = """
        local key = KEYS[1]
        local from_number = ARGV[1]
        local score = redis.call('ZSCORE', key, from_number)
        if score then
            redis.call('ZADD', key, 0, from_number)
            return 1
        end
        return 0
        """
        result = await redis_client.eval(lua_script, 1, key, from_number)
        return bool(result)

    async def store_call_slot_mapping_if_absent(
        self,
        call_id: str,
        organization_id: str,
        slot_id: str,
        scope_key: str | None = None,
    ) -> bool:
        redis_client = await self._get_redis()
        mapping_key = f"call_slot_mapping:{call_id}"
        lua_script = """
        local key = KEYS[1]
        local org_id = ARGV[1]
        local slot_id = ARGV[2]
        local ttl = tonumber(ARGV[3])
        local scope_key = ARGV[4]
        if redis.call('EXISTS', key) == 1 then
            return 0
        end
        redis.call('HSET', key, 'org_id', org_id, 'slot_id', slot_id)
        if scope_key ~= '' then
            redis.call('HSET', key, 'scope_key', scope_key)
        end
        redis.call('EXPIRE', key, ttl)
        return 1
        """
        stored = await redis_client.eval(
            lua_script,
            1,
            mapping_key,
            organization_id,
            slot_id,
            self.stale_call_timeout,
            scope_key or "",
        )
        return bool(stored)

    async def get_call_slot_mapping(
        self, call_id: str
    ) -> tuple[str, str, str | None] | None:
        redis_client = await self._get_redis()
        mapping_key = f"call_slot_mapping:{call_id}"
        mapping = await redis_client.hgetall(mapping_key)
        if mapping and "org_id" in mapping and "slot_id" in mapping:
            return (
                str(mapping["org_id"]),
                str(mapping["slot_id"]),
                mapping.get("scope_key") or None,
            )
        return None

    async def delete_call_slot_mapping(self, call_id: str) -> bool:
        redis_client = await self._get_redis()
        mapping_key = f"call_slot_mapping:{call_id}"
        deleted = await redis_client.delete(mapping_key)
        return bool(deleted)

    async def store_call_from_number_mapping(
        self,
        call_id: str,
        organization_id: str,
        from_number: str,
        pool_scope: str,
    ) -> bool:
        redis_client = await self._get_redis()
        mapping_key = f"call_from_number:{call_id}"
        await redis_client.hset(
            mapping_key,
            mapping={
                "org_id": organization_id,
                "from_number": from_number,
                "pool_scope": pool_scope,
            },
        )
        await redis_client.expire(mapping_key, 1800)
        return True

    async def get_call_from_number_mapping(
        self, call_id: str
    ) -> tuple[str, str, str] | None:
        redis_client = await self._get_redis()
        mapping_key = f"call_from_number:{call_id}"
        mapping = await redis_client.hgetall(mapping_key)
        if mapping and "org_id" in mapping and "from_number" in mapping:
            return (
                str(mapping["org_id"]),
                str(mapping["from_number"]),
                str(mapping.get("pool_scope") or ""),
            )
        return None

    async def delete_call_from_number_mapping(self, call_id: str) -> bool:
        redis_client = await self._get_redis()
        mapping_key = f"call_from_number:{call_id}"
        deleted = await redis_client.delete(mapping_key)
        return bool(deleted)


rate_limiter = RateLimiter()
