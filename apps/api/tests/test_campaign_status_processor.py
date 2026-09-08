"""Campaign status processor tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.campaign.status_processor import handle_call_terminal


@pytest.mark.asyncio
async def test_handle_call_terminal_releases_slot_without_campaign() -> None:
    with patch(
        "app.services.campaign.status_processor.campaign_call_dispatcher.release_call_slot",
        new_callable=AsyncMock,
    ) as release:
        await handle_call_terminal(
            call_id="call-1",
            campaign_id=None,
            queued_run_id=None,
            call_response="busy",
        )
        release.assert_awaited_once_with("call-1")


@pytest.mark.asyncio
async def test_handle_call_terminal_publishes_retry_on_busy() -> None:
    with (
        patch(
            "app.services.campaign.status_processor.campaign_call_dispatcher.release_call_slot",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.campaign.status_processor.circuit_breaker.record_and_evaluate",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.campaign.status_processor.repo.get_campaign_by_id",
            return_value={
                "campaign_id": "camp-1",
                "retry_config": {
                    "enabled": True,
                    "retry_on_busy": True,
                    "retry_on_no_answer": True,
                    "retry_on_voicemail": False,
                },
            },
        ),
        patch(
            "app.services.campaign.status_processor.get_campaign_event_publisher",
            new_callable=AsyncMock,
        ) as publisher_factory,
    ):
        publisher = AsyncMock()
        publisher_factory.return_value = publisher
        await handle_call_terminal(
            call_id="call-1",
            campaign_id="camp-1",
            queued_run_id="qr-1",
            call_response="busy",
        )
        publisher.publish_retry_needed.assert_awaited_once()
