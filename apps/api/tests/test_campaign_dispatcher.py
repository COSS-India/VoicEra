"""Campaign call dispatcher tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.call_concurrency import CallConcurrencySlot
from app.services.campaign.campaign_call_dispatcher import CampaignCallDispatcher


@pytest.mark.asyncio
async def test_process_batch_returns_zero_when_not_running() -> None:
    dispatcher = CampaignCallDispatcher()
    with patch(
        "app.services.campaign.campaign_call_dispatcher.repo.get_campaign_by_id",
        return_value={"campaign_id": "c1", "state": "paused"},
    ):
        count = await dispatcher.process_batch("c1")
    assert count == 0


@pytest.mark.asyncio
async def test_dispatch_call_links_call_log() -> None:
    dispatcher = CampaignCallDispatcher()
    campaign = {
        "campaign_id": "c1",
        "org_id": "org-1",
        "agent_id": "agent-1",
    }
    queued_run = {
        "queued_run_id": "q1",
        "source_uuid": "row_1",
        "context_variables": {"phone_number": "+14155551234", "name": "Jane"},
    }
    slot = CallConcurrencySlot(
        organization_id="org-1",
        slot_id="slot-1",
        max_concurrent=5,
        source="campaign",
        scope_key="campaign:c1",
    )

    with (
        patch.object(
            dispatcher,
            "acquire_from_number",
            new_callable=AsyncMock,
            return_value=("+15551234567", False),
        ),
        patch(
            "app.services.campaign.campaign_call_dispatcher.initiate_outbound_call",
            new_callable=AsyncMock,
            return_value={"call_id": "call-99"},
        ),
        patch(
            "app.services.campaign.campaign_call_dispatcher.call_log_service.update_call_log"
        ) as update_log,
        patch(
            "app.services.campaign.campaign_call_dispatcher.call_concurrency.bind_call_slot",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.campaign.campaign_call_dispatcher.rate_limiter.store_call_from_number_mapping",
            new_callable=AsyncMock,
        ),
    ):
        result = await dispatcher.dispatch_call(queued_run, campaign, slot)
        assert result["call_id"] == "call-99"
        update_log.assert_called_once()
        assert update_log.call_args[0][1]["campaign_id"] == "c1"


@pytest.mark.asyncio
async def test_acquire_from_number_reuses_single_cli_without_pool() -> None:
    dispatcher = CampaignCallDispatcher()
    campaign = {
        "campaign_id": "c1",
        "from_number": "+918065480891",
    }

    with patch.object(
        dispatcher,
        "_resolve_from_numbers",
        new_callable=AsyncMock,
        return_value=["+918065480891"],
    ):
        first, first_managed = await dispatcher.acquire_from_number(
            "org-1", "agent-1", campaign
        )
        second, second_managed = await dispatcher.acquire_from_number(
            "org-1", "agent-1", campaign
        )

    assert first == "+918065480891"
    assert second == "+918065480891"
    assert first_managed is False
    assert second_managed is False


@pytest.mark.asyncio
async def test_dispatch_call_skips_pool_mapping_for_single_cli() -> None:
    dispatcher = CampaignCallDispatcher()
    campaign = {
        "campaign_id": "c1",
        "org_id": "org-1",
        "agent_id": "agent-1",
        "from_number": "+918065480891",
    }
    queued_run = {
        "queued_run_id": "q1",
        "source_uuid": "row_1",
        "context_variables": {"phone_number": "+14155551234"},
    }
    slot = CallConcurrencySlot(
        organization_id="org-1",
        slot_id="slot-1",
        max_concurrent=5,
        source="campaign",
        scope_key="campaign:c1",
    )

    with (
        patch.object(
            dispatcher,
            "acquire_from_number",
            new_callable=AsyncMock,
            return_value=("+918065480891", False),
        ),
        patch(
            "app.services.campaign.campaign_call_dispatcher.initiate_outbound_call",
            new_callable=AsyncMock,
            return_value={"call_id": "call-99"},
        ),
        patch(
            "app.services.campaign.campaign_call_dispatcher.call_log_service.update_call_log"
        ),
        patch(
            "app.services.campaign.campaign_call_dispatcher.call_concurrency.bind_call_slot",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.campaign.campaign_call_dispatcher.rate_limiter.store_call_from_number_mapping",
            new_callable=AsyncMock,
        ) as store_mapping,
    ):
        await dispatcher.dispatch_call(queued_run, campaign, slot)
        store_mapping.assert_not_called()
