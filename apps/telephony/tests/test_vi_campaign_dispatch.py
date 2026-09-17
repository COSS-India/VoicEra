"""VI bulk campaign dispatch tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.telephony.providers.vi.campaign_dispatch import process_vi_batch
from apps.telephony.providers.vi.client import ViClient
from apps.telephony.providers.vi.config import ViConfig, ViNumberFlowEntry


def _vi_client() -> ViClient:
    cfg = ViConfig(
        obd_username="user",
        obd_password="pass",
        number_flows=[
            ViNumberFlowEntry(
                phone_number="+919876543210",
                flow_id="flow-abc",
            )
        ],
    )
    return ViClient(cfg)


@pytest.mark.asyncio
@patch("apps.telephony.providers.vi.campaign_dispatch.asyncio.sleep", new_callable=AsyncMock)
@patch("apps.telephony.providers.vi.campaign_dispatch.asyncio.to_thread")
async def test_process_vi_batch_uses_single_create_campaign(
    to_thread_mock: MagicMock,
    _sleep_mock: AsyncMock,
) -> None:
    client = _vi_client()
    campaign = {
        "org_id": "org-1",
        "agent_id": "agent-1",
        "campaign_id": "camp-1",
        "processed_rows": 0,
        "orchestrator_metadata": {},
    }
    queued_runs = [
        {
            "queued_run_id": "q1",
            "context_variables": {"phone_number": "+919111111111"},
        },
        {
            "queued_run_id": "q2",
            "context_variables": {"phone_number": "+919222222222"},
        },
    ]

    to_thread_mock.side_effect = [
        {
            "dni": "9876543210",
            "dni_source": "configured_phone",
            "campainKey": "key-1",
            "campaign_Ref_ID": "ref-1",
            "token": "token-1",
        },
        (
            {
                "data": {
                    "currentStatus": "Completed",
                    "baseDetails": {
                        "totalCallInitiated": 2,
                        "totalCallsConnected": 1,
                        "totalCallsNotConnected": 1,
                        "remainingNumbersInQueue": 0,
                    },
                }
            },
            "campaign_Ref_ID",
        ),
    ]

    updates: list[tuple[str, dict[str, Any]]] = []
    call_logs: list[dict[str, Any]] = []

    count = await process_vi_batch(
        campaign,
        queued_runs,
        client=client,
        agent={"name": "Agent"},
        from_number="+919876543210",
        update_queued_run=lambda qid, **kwargs: updates.append((qid, kwargs)),
        update_campaign=lambda cid, **kwargs: None,
        create_call_log=lambda doc: call_logs.append(doc),
        get_campaign=lambda _cid: campaign,
    )

    assert count == 2
    assert len(call_logs) == 2
    assert to_thread_mock.call_count == 2
    obd_fn = to_thread_mock.call_args_list[0].args[0]
    assert callable(obd_fn)
