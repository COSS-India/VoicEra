"""ARQ cron task that sends due post-call webhooks."""

from __future__ import annotations

import logging
from typing import Any

from app.services import call_webhook_service

logger = logging.getLogger(__name__)


async def dispatch_call_webhooks(ctx: dict[str, Any]) -> int:
    sent = await call_webhook_service.dispatch_due()
    if sent:
        logger.info("Dispatched %s call webhook(s)", sent)
    return sent
