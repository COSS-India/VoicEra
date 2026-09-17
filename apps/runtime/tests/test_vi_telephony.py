"""VI /vi/stream WebSocket routing tests."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def _vi_agent() -> dict[str, Any]:
    return {
        "agent_id": "agent-vi",
        "org_id": "org-1",
        "name": "VI Agent",
        "agent_category": "telephony",
        "telephony": {"provider": "vi"},
    }


def _vi_start_payload() -> str:
    return json.dumps(
        {
            "event": "start",
            "room_id": "room-1",
            "call_id": "call-vi-1",
            "start": {
                "dni": "9876543210",
                "cli": "9123456789",
                "room_id": "room-1",
                "call_id": "call-vi-1",
            },
        }
    )


@patch("apps.runtime.routes.agent.run_telephony_bot", new_callable=AsyncMock)
@patch(
    "apps.runtime.routes.agent.backend_client.create_inbound_call",
    new_callable=AsyncMock,
    return_value={"call_id": "log-1"},
)
@patch(
    "apps.runtime.routes.agent.backend_client.get_agent_by_phone",
    new_callable=AsyncMock,
)
def test_vi_stream_happy_path(
    get_by_phone_mock: AsyncMock,
    _create_inbound: AsyncMock,
    run_bot_mock: AsyncMock,
    client: TestClient,
) -> None:
    get_by_phone_mock.return_value = _vi_agent()

    with client.websocket_connect("/vi/stream") as websocket:
        websocket.send_text(json.dumps({"event": "connected"}))
        websocket.send_text(_vi_start_payload())

    get_by_phone_mock.assert_awaited_once_with("9876543210")
    run_bot_mock.assert_awaited_once()
    kwargs = run_bot_mock.await_args.kwargs
    assert kwargs["provider"] == "vi"
    assert kwargs["org_id"] == "org-1"
    assert kwargs["stream_sid"] == "room-1"
    assert kwargs["call_sid"] == "call-vi-1"
    assert kwargs["call_id"] == "log-1"


@patch("apps.runtime.routes.agent.run_telephony_bot", new_callable=AsyncMock)
@patch(
    "apps.runtime.routes.agent.backend_client.get_agent_by_phone",
    new_callable=AsyncMock,
)
def test_vi_stream_missing_agent_closes(
    get_by_phone_mock: AsyncMock,
    run_bot_mock: AsyncMock,
    client: TestClient,
) -> None:
    get_by_phone_mock.return_value = None

    with client.websocket_connect("/vi/stream") as websocket:
        websocket.send_text(json.dumps({"event": "connected"}))
        websocket.send_text(_vi_start_payload())
        close = websocket.receive()
        assert close.get("type") == "websocket.close"
        assert close.get("code") == 1008

    run_bot_mock.assert_not_awaited()
