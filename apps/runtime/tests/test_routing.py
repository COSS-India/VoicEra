"""Runtime routing tests for telephony vs websocket agents."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


def _telephony_agent(provider: str = "plivo") -> dict[str, Any]:
    return {
        "agent_id": "agent-1",
        "org_id": "org-1",
        "name": "Tel Agent",
        "agent_category": "telephony",
        "telephony": {"provider": provider},
    }


def _websocket_agent() -> dict[str, Any]:
    return {
        "agent_id": "agent-2",
        "org_id": "org-1",
        "name": "WS Agent",
        "agent_category": "websocket",
        "telephony": None,
    }


@patch("apps.runtime.routes.telephony.backend_client.get_agent", new_callable=AsyncMock)
def test_answer_rejects_websocket_agent(
    get_agent_mock: AsyncMock,
    client: TestClient,
) -> None:
    get_agent_mock.return_value = _websocket_agent()

    response = client.post(
        "/answer",
        params={"agent_id": "agent-2", "org_id": "org-1"},
        data={"event": "answer"},
    )

    assert response.status_code == 400
    assert "telephony" in response.text.lower()


@patch("apps.runtime.routes.telephony.backend_client.get_agent", new_callable=AsyncMock)
def test_answer_uses_agent_provider(
    get_agent_mock: AsyncMock,
    client: TestClient,
) -> None:
    get_agent_mock.return_value = _telephony_agent(provider="plivo")

    response = client.post(
        "/answer",
        params={"agent_id": "agent-1", "org_id": "org-1"},
        data={"event": "answer"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/xml")
    assert "/agent/org-1/agent-1" in response.text
    assert "<Stream" in response.text


@patch("apps.runtime.routes.agent.run_websocket_bot", new_callable=AsyncMock)
@patch("apps.runtime.routes.agent.backend_client.create_web_call", new_callable=AsyncMock)
@patch("apps.runtime.routes.agent.backend_client.get_agent", new_callable=AsyncMock)
def test_websocket_agent_auto_creates_call_id(
    get_agent_mock: AsyncMock,
    create_web_call_mock: AsyncMock,
    run_websocket_bot_mock: AsyncMock,
    client: TestClient,
) -> None:
    agent = _websocket_agent()
    get_agent_mock.return_value = agent
    create_web_call_mock.return_value = {"call_id": "call-web-1"}

    with client.websocket_connect("/agent/org-1/agent-2") as websocket:
        websocket.close()

    create_web_call_mock.assert_awaited_once_with("org-1", "agent-2")
    run_websocket_bot_mock.assert_awaited_once()
    _, kwargs = run_websocket_bot_mock.await_args
    assert kwargs["call_id"] == "call-web-1"
    assert kwargs["org_id"] == "org-1"
    assert kwargs["agent"] == agent


@patch("apps.runtime.routes.agent.run_websocket_bot", new_callable=AsyncMock)
@patch("apps.runtime.routes.agent.backend_client.create_web_call", new_callable=AsyncMock)
@patch("apps.runtime.routes.agent.backend_client.get_call", new_callable=AsyncMock)
@patch("apps.runtime.routes.agent.backend_client.get_agent", new_callable=AsyncMock)
def test_websocket_agent_reuses_query_call_id(
    get_agent_mock: AsyncMock,
    get_call_mock: AsyncMock,
    create_web_call_mock: AsyncMock,
    run_websocket_bot_mock: AsyncMock,
    client: TestClient,
) -> None:
    agent = _websocket_agent()
    get_agent_mock.return_value = agent
    get_call_mock.return_value = {
        "call_id": "call-web-existing",
        "call_type": "web",
        "agent_id": "agent-2",
        "custom_variables": {"name": "Jane"},
    }

    with client.websocket_connect(
        "/agent/org-1/agent-2?call_id=call-web-existing"
    ) as websocket:
        websocket.close()

    create_web_call_mock.assert_not_awaited()
    get_call_mock.assert_awaited_once_with("call-web-existing", "org-1")
    run_websocket_bot_mock.assert_awaited_once()
    _, kwargs = run_websocket_bot_mock.await_args
    assert kwargs["call_id"] == "call-web-existing"
    assert kwargs["custom_variables"] == {"name": "Jane"}


@patch("apps.runtime.routes.agent.run_telephony_bot", new_callable=AsyncMock)
@patch("apps.runtime.routes.agent.backend_client.get_agent", new_callable=AsyncMock)
def test_telephony_agent_routes_to_telephony_bot(
    get_agent_mock: AsyncMock,
    run_telephony_bot_mock: AsyncMock,
    client: TestClient,
) -> None:
    agent = _telephony_agent(provider="vobiz")
    get_agent_mock.return_value = agent

    start_payload = {
        "event": "start",
        "start": {
            "callSid": "call-123",
            "streamSid": "stream-456",
        },
    }

    with client.websocket_connect("/agent/org-1/agent-1") as websocket:
        websocket.send_json(start_payload)
        websocket.close()

    run_telephony_bot_mock.assert_awaited_once()
    _, kwargs = run_telephony_bot_mock.await_args
    assert kwargs["provider"] == "vobiz"
    assert kwargs["call_sid"] == "call-123"
    assert kwargs["stream_sid"] == "stream-456"
    assert kwargs["agent"] == agent


@patch("apps.runtime.routes.agent.run_telephony_bot", new_callable=AsyncMock)
@patch("apps.runtime.routes.agent.backend_client.get_agent", new_callable=AsyncMock)
def test_telephony_agent_missing_provider_closes_socket(
    get_agent_mock: AsyncMock,
    run_telephony_bot_mock: AsyncMock,
    client: TestClient,
) -> None:
    agent = _telephony_agent()
    agent["telephony"] = {}
    get_agent_mock.return_value = agent

    with client.websocket_connect("/agent/org-1/agent-1"):
        pass

    run_telephony_bot_mock.assert_not_awaited()
