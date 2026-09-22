"""Service-level tests for agent telephony helpers and agent_service."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.schemas import AgentCreateRequest, AgentUpdateRequest, AgentConfigPayload
from app.services.agent_config_validation import AgentConfigValidationError
from app.services import agent_service
from app.services.agent_telephony_service import (
    AgentTelephonyError,
    build_answer_urls,
    get_provider_dial_credentials,
    load_telephony_client,
    provision_application,
)
from app.services.agent_service import AgentNotFoundError


def _valid_config() -> AgentConfigPayload:
    return AgentConfigPayload.model_validate(
        {
            "prompts": {
                "system_prompt": "You are helpful.",
                "greeting_message": "Hello!",
            },
            "language": {"primary": "en", "secondary": []},
            "models": {
                "stt_config": {"provider": "openai", "model": "gpt-4o-transcribe"},
                "tts_config": {
                    "provider": "openai",
                    "model": "gpt-4o-mini-tts",
                    "voice": "alloy",
                },
                "llm_config": {"provider": "openai", "model": "gpt-4o-mini"},
            },
        }
    )


@patch("app.services.agent_telephony_service.settings")
def test_build_answer_urls(settings_mock: MagicMock) -> None:
    settings_mock.VOICE_SERVER_BASE_URL = "https://voice.example.com/"
    answer_url, hangup_url = build_answer_urls("org-1", "abc-123")
    assert answer_url == "https://voice.example.com/answer?agent_id=abc-123&org_id=org-1"
    assert hangup_url == answer_url


@patch("app.services.agent_telephony_service.settings")
def test_build_answer_urls_missing_config(settings_mock: MagicMock) -> None:
    settings_mock.VOICE_SERVER_BASE_URL = ""
    with pytest.raises(AgentTelephonyError, match="VOICE_SERVER_BASE_URL"):
        build_answer_urls("org-1", "abc-123")


@pytest.mark.asyncio
@patch("app.services.agent_telephony_service.load_telephony_client")
@patch("app.services.agent_telephony_service.build_answer_urls")
async def test_provision_application_success(
    build_urls_mock: MagicMock,
    load_client_mock: MagicMock,
) -> None:
    build_urls_mock.return_value = (
        "https://voice.example.com/answer?agent_id=x&org_id=org-1",
        "https://voice.example.com/answer?agent_id=x&org_id=org-1",
    )
    client = AsyncMock()
    client.create_application.return_value = {
        "status": "success",
        "app_id": "app-99",
    }
    load_client_mock.return_value = client

    attachment = await provision_application("org-1", "vobiz", "agent-x")
    assert attachment["provider"] == "vobiz"
    assert attachment["application_id"] == "app-99"
    assert attachment["hangup_url"] == attachment["answer_url"]
    client.create_application.assert_awaited_once_with(
        "agent-x",
        "https://voice.example.com/answer?agent_id=x&org_id=org-1",
    )


@pytest.mark.asyncio
@patch("app.services.agent_service.get_database")
@patch("app.services.agent_service.agent_telephony_service.provision_application", new_callable=AsyncMock)
async def test_create_agent_telephony_calls_provision(
    provision_mock: AsyncMock,
    db_mock: MagicMock,
) -> None:
    provision_mock.return_value = {
        "provider": "vobiz",
        "application_id": "app-1",
        "answer_url": "https://voice.example.com/answer?agent_id=agent-id&org_id=org-1",
    }
    collection = MagicMock()
    collection.insert_one.return_value = None
    db_mock.return_value = {"Agents": collection}

    payload = AgentCreateRequest(
        name="Tel Agent",
        agent_category="telephony",
        telephony_provider="vobiz",
        config=_valid_config(),
    )
    result = await agent_service.create_agent("org-1", "admin@example.com", payload)
    assert result["telephony"]["application_id"] == "app-1"
    provision_mock.assert_awaited_once()


@pytest.mark.asyncio
@patch("app.services.agent_service.get_database")
async def test_update_agent_not_found(db_mock: MagicMock) -> None:
    collection = MagicMock()
    collection.find_one.return_value = None
    db_mock.return_value = {"Agents": collection}

    with pytest.raises(AgentNotFoundError):
        await agent_service.update_agent(
            "org-1",
            "missing",
            AgentUpdateRequest(name="New"),
        )


@pytest.mark.asyncio
async def test_create_websocket_rejects_telephony_provider() -> None:
    payload = AgentCreateRequest(
        name="WS Agent",
        agent_category="websocket",
        telephony_provider="vobiz",
        config=_valid_config(),
    )
    with pytest.raises(AgentConfigValidationError):
        await agent_service.create_agent("org-1", "admin@example.com", payload)


@patch("app.services.agent_telephony_service.auth_service.get_provider_auth")
def test_vi_load_telephony_client_requires_provider_auth(
    get_auth_mock: MagicMock,
) -> None:
    import apps.telephony.providers.vi.config  # noqa: F401 — register provider

    get_auth_mock.return_value = None
    with pytest.raises(AgentTelephonyError, match="not configured"):
        load_telephony_client("org-1", "vi")


@patch("app.services.agent_telephony_service.auth_service.get_provider_auth")
def test_vi_load_telephony_client_from_provider_auth(
    get_auth_mock: MagicMock,
) -> None:
    import apps.telephony.providers.vi.config  # noqa: F401

    get_auth_mock.return_value = {
        "auth": {
            "auth_id": "auth-user",
            "auth_token": "auth-pass",
            "dni_flows": '[{"dni":"919876543210","flow_id":"flow-a"}]',
        }
    }
    client = load_telephony_client("org-1", "vi")
    assert client.credentials.auth_id == "auth-user"
    assert client.dni_flows[0]["flow_id"] == "flow-a"


@patch("app.services.agent_telephony_service.auth_service.get_provider_auth")
def test_vi_get_provider_dial_credentials_from_auth(
    get_auth_mock: MagicMock,
) -> None:
    import apps.telephony.providers.vi.config  # noqa: F401

    get_auth_mock.return_value = {
        "auth": {
            "auth_id": "auth-user",
            "auth_token": "auth-pass",
            "dni_flows": '[{"dni":"919876543210","flow_id":"flow-a"}]',
        }
    }
    creds = get_provider_dial_credentials("org-1", "vi")
    assert creds["auth_id"] == "auth-user"
    assert "dni_flows" in creds


@patch("app.services.agent_telephony_service.auth_service.get_provider_auth")
def test_vi_client_default_from_number_from_auth(
    get_auth_mock: MagicMock,
) -> None:
    import apps.telephony.providers.vi.config  # noqa: F401

    get_auth_mock.return_value = {
        "auth": {
            "auth_id": "u",
            "auth_token": "p",
            "dni_flows": '[{"dni":"919769554706","flow_id":"flow-a"}]',
        }
    }
    client = load_telephony_client("org-1", "vi")
    assert client.default_from_number() == "+919769554706"
