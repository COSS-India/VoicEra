"""ARQ worker configuration."""

from __future__ import annotations

from urllib.parse import urlparse

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings

from app.config import settings
from app.tasks.campaign_tasks import process_campaign_batch, sync_campaign_source
from app.tasks.function_names import FunctionNames

parsed_url = urlparse(settings.REDIS_URL)
use_ssl = parsed_url.scheme == "rediss"

REDIS_SETTINGS = RedisSettings(
    host=parsed_url.hostname or "localhost",
    port=parsed_url.port or 6379,
    password=parsed_url.password,
    conn_timeout=10,
    ssl=use_ssl,
    ssl_check_hostname=False if use_ssl else None,
)


class WorkerSettings:
    functions = [sync_campaign_source, process_campaign_batch]
    redis_settings = REDIS_SETTINGS
    max_jobs = 10


_redis_pool: ArqRedis | None = None


async def get_arq_redis() -> ArqRedis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = await create_pool(REDIS_SETTINGS)
    return _redis_pool


async def enqueue_job(function_name: FunctionNames, *args, **kwargs):
    redis = await get_arq_redis()
    return await redis.enqueue_job(function_name.value, *args, **kwargs)
