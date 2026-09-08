"""Handle terminal call outcomes for campaign retries and circuit breaker."""

from __future__ import annotations

import logging

from app.services.campaign import campaign_repository as repo
from app.services.campaign.campaign_call_dispatcher import campaign_call_dispatcher
from app.services.campaign.campaign_event_publisher import get_campaign_event_publisher
from app.services.campaign.circuit_breaker import circuit_breaker

logger = logging.getLogger(__name__)

RETRYABLE = frozenset({"busy", "no_answer", "voicemail", "failed"})
FAILURE_RESPONSES = frozenset({"busy", "no_answer", "voicemail", "failed", "cancelled"})


async def handle_call_terminal(
    *,
    call_id: str,
    campaign_id: str | None,
    queued_run_id: str | None,
    call_response: str | None,
) -> None:
    await campaign_call_dispatcher.release_call_slot(call_id)
    if not campaign_id:
        return

    response = str(call_response or "").strip().lower()
    is_failure = response in FAILURE_RESPONSES
    await circuit_breaker.record_and_evaluate(
        campaign_id,
        is_failure=is_failure,
        call_id=call_id if is_failure else None,
        reason=response if is_failure else None,
    )

    if not is_failure or response not in RETRYABLE or not queued_run_id:
        return

    campaign = repo.get_campaign_by_id(campaign_id)
    if not campaign:
        return
    retry_config = campaign.get("retry_config") or {}
    if not retry_config.get("enabled", True):
        return
    if response == "busy" and not retry_config.get("retry_on_busy", True):
        return
    if response == "no_answer" and not retry_config.get("retry_on_no_answer", True):
        return
    if response == "voicemail" and not retry_config.get("retry_on_voicemail", False):
        return

    publisher = await get_campaign_event_publisher()
    await publisher.publish_retry_needed(
        call_id=call_id,
        reason=response,
        campaign_id=campaign_id,
        queued_run_id=queued_run_id,
    )
