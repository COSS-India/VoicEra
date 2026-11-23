"""Event log retention."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.eventlog import store

logger = logging.getLogger(__name__)


async def purge_events(ctx: dict[str, Any]) -> int:
    """Delete events older than EVENTLOG_RETENTION_DAYS (never below 365)."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.EVENTLOG_RETENTION_DAYS)
    deleted = await asyncio.to_thread(store.purge, cutoff)
    logger.info("Purged %d events created before %s", deleted, cutoff.isoformat())
    return deleted
