"""VI outbound dial path tests (org-scoped telephony client)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.agent_telephony_service import AgentTelephonyError
from app.services.outbound_call_service import OutboundCallError, initiate_outbound_call


def _vi_agent(**overrides: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "agent_id": "agent-vi",
        "org_id": "org-1",
        "name": "VI Agent",
        "status": "active",
        "agent_category": "telephony",
        "linked_phone_number": "+919876543210",
        "telephony": {
            "provider": "vi",
            "application_id": "vi-local",
            "answer_url": "https://voice.example.com/answer?agent_id=agent-vi&org_id=org-1",
        },
    }
    doc.update(overrides)
    return doc


@pytest.fixture(autouse=True)
def patch_voice_server_url() -> None:
    with patch(
        "app.services.agent_telephony_service.settings.VOICE_SERVER_BASE_URL",
        "https://voice.example.com",
    ):
        yield


@pytest.mark.asyncio
@patch("app.services.outbound_call_service.call_log_service.create_call_log")
@patch("app.services.outbound_call_service.call_log_service.update_call_log")
@patch("app.services.outbound_call_service.agent_service.get_agent")
@patch("app.services.outbound_call_service.load_telephony_client")
@patch(
    "app.services.outbound_call_service.require_phone_in_provider_inventory",
)
async def test_vi_outbound_happy_path(
    _require_inventory: MagicMock,
    load_client_mock: MagicMock,
    get_agent_mock: MagicMock,
    update_log_mock: MagicMock,
    create_log_mock: MagicMock,
) -> None:
    get_agent_mock.return_value = _vi_agent()
    create_log_mock.side_effect = lambda doc: doc
    update_log_mock.side_effect = lambda _call_id, patch: patch

    mock_client = MagicMock()
    mock_client.initiate_call = AsyncMock(
        return_value={
            "status": "success",
            "message": "VI outbound queued",
            "call_uuid": "ref-99",
            "request_uuid": "ref-99",
            "campaign_Ref_ID": "ref-99",
        }
    )
    load_client_mock.return_value = mock_client

    result = await initiate_outbound_call(
        "org-1",
        "agent-vi",
        "+919123456789",
    )

    assert result["status"] == "ringing"
    assert result["provider_call_sid"] == "ref-99"
    _require_inventory.assert_called_once_with(
        "org-1", "vi", "+919876543210"
    )
    mock_client.initiate_call.assert_awaited_once()
    dial_kwargs = mock_client.initiate_call.await_args.kwargs
    assert dial_kwargs["from_number"] == "+919876543210"
    assert dial_kwargs["to_number"] == "+919123456789"
    assert "agent_id=agent-vi" in dial_kwargs["answer_url"]


@pytest.mark.asyncio
@patch("app.services.outbound_call_service.call_log_service.create_call_log")
@patch("app.services.outbound_call_service.call_log_service.update_call_log")
@patch("app.services.outbound_call_service.agent_service.get_agent")
@patch("app.services.outbound_call_service.load_telephony_client")
@patch(
    "app.services.outbound_call_service.require_phone_in_provider_inventory",
    side_effect=AgentTelephonyError(
        "No VI flow_id configured for phone +919999999999. "
        "Configure this phone in Integrations → Vodafone Idea.",
        status_code=422,
    ),
)
async def test_vi_outbound_rejects_unknown_caller_id(
    _require_inventory: MagicMock,
    load_client_mock: MagicMock,
    get_agent_mock: MagicMock,
    update_log_mock: MagicMock,
    create_log_mock: MagicMock,
) -> None:
    get_agent_mock.return_value = _vi_agent(linked_phone_number="+919999999999")
    create_log_mock.side_effect = lambda doc: doc
    update_log_mock.side_effect = lambda _call_id, patch: patch
    mock_client = MagicMock()
    mock_client.initiate_call = AsyncMock()
    load_client_mock.return_value = mock_client

    with pytest.raises(OutboundCallError, match="Integrations"):
        await initiate_outbound_call(
            "org-1",
            "agent-vi",
            "+919123456789",
        )

    load_client_mock.assert_called_once()
    mock_client.initiate_call.assert_not_called()
