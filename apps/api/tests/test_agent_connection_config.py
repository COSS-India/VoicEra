"""Agent config rules for connection-based LLM providers."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from app.models.schemas import AgentConfigPayload
from app.services.agent_config_validation import (
    AgentConfigValidationError,
    validate_agent_config,
)


def _config(llm: dict[str, Any], **overrides: Any) -> AgentConfigPayload:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "prompts": {"system_prompt": "You are helpful.", "greeting_message": "Hi!"},
        "behaviour": {},
        "language": {"primary": "en", "secondary": []},
        "models": {
            "stt_config": {"provider": "openai", "model": "gpt-4o-transcribe"},
            "tts_config": {
                "provider": "openai",
                "model": "gpt-4o-mini-tts",
                "voice": "alloy",
            },
            "llm_config": llm,
        },
        "knowledge_base": {"enabled": False, "document_ids": [], "top_k": 5},
    }
    payload.update(overrides)
    return AgentConfigPayload.model_validate(payload)


_LLM = {
    "provider": "openai_compatible",
    "connection_id": "conn-1",
    "model": "Qwen/Qwen3-8B-Instruct",
    "temperature": 0.4,
}


def test_connection_id_is_required():
    config = _config({"provider": "openai_compatible", "model": "qwen"})
    with pytest.raises(AgentConfigValidationError) as exc:
        validate_agent_config(config, org_id="org-1")
    assert "connection_id is required" in str(exc.value)


def test_unknown_connection_is_rejected():
    with patch(
        "app.services.provider_connection_service.connection_exists",
        return_value=False,
    ):
        with pytest.raises(AgentConfigValidationError) as exc:
            validate_agent_config(_config(_LLM), org_id="org-1")
    assert "conn-1" in str(exc.value)


def test_known_connection_is_kept_without_endpoint_or_key():
    with patch(
        "app.services.provider_connection_service.connection_exists",
        return_value=True,
    ):
        validated = validate_agent_config(_config(_LLM), org_id="org-1")
    llm = validated.models.llm_config
    assert llm["connection_id"] == "conn-1"
    assert llm["temperature"] == 0.4
    # Endpoint and key stay on the connection, never on the agent.
    assert "base_url" not in llm
    assert "api_key" not in llm


def test_endpoint_or_key_in_the_agent_payload_is_refused():
    config = _config({**_LLM, "base_url": "http://evil.example.com/v1"})
    with pytest.raises(AgentConfigValidationError) as exc:
        validate_agent_config(config, org_id="org-1")
    assert "base_url" in str(exc.value)


def test_the_agents_own_history_mode_is_saved():
    with patch(
        "app.services.provider_connection_service.connection_exists",
        return_value=True,
    ):
        validated = validate_agent_config(
            _config({**_LLM, "history_mode": "current_turn"}), org_id="org-1"
        )
    assert validated.models.llm_config["history_mode"] == "current_turn"


def test_an_agent_that_says_nothing_inherits_the_endpoint():
    with patch(
        "app.services.provider_connection_service.connection_exists",
        return_value=True,
    ):
        validated = validate_agent_config(_config(_LLM), org_id="org-1")
    assert validated.models.llm_config["history_mode"] == "inherit"


def test_the_agents_own_system_prompt_mode_is_saved():
    with patch(
        "app.services.provider_connection_service.connection_exists",
        return_value=True,
    ):
        validated = validate_agent_config(
            _config({**_LLM, "system_prompt_mode": "omit"}), org_id="org-1"
        )
    assert validated.models.llm_config["system_prompt_mode"] == "omit"


@pytest.mark.parametrize(
    "field",
    [
        "endpoint_history_mode",
        "endpoint_system_prompt_mode",
        "endpoint_send_caller_phone",
        "caller_phone",
    ],
)
def test_the_endpoints_own_defaults_are_refused_on_the_agent(field):
    """They belong to the connection, so they are auth-layer fields like base_url."""
    config = _config({**_LLM, field: "omit"})
    with pytest.raises(AgentConfigValidationError) as exc:
        validate_agent_config(config, org_id="org-1")
    assert field in str(exc.value)


def test_kb_tool_mode_follows_the_endpoint_flag_not_the_provider_id():
    """A vendor id says nothing about what an operator pointed the URL at."""
    config = _config(
        _LLM,
        knowledge_base={"enabled": True, "document_ids": ["doc-1"], "top_k": 5, "mode": "tool"},
    )
    with (
        patch(
            "app.services.provider_connection_service.connection_exists",
            return_value=True,
        ),
        patch(
            "app.services.provider_connection_service.supports_tools",
            return_value=False,
        ),
        patch("app.services.knowledge_service.assert_documents_ready"),
    ):
        with pytest.raises(AgentConfigValidationError) as exc:
            validate_agent_config(config, org_id="org-1")
    assert "function calling" in str(exc.value)

    with (
        patch(
            "app.services.provider_connection_service.connection_exists",
            return_value=True,
        ),
        patch(
            "app.services.provider_connection_service.supports_tools",
            return_value=True,
        ),
        patch("app.services.knowledge_service.assert_documents_ready"),
    ):
        validated = validate_agent_config(config, org_id="org-1")
    assert validated.knowledge_base.mode == "tool"


def test_vendor_providers_keep_their_existing_tool_gate():
    config = _config(
        {"provider": "sarvam", "model": "sarvam-105b"},
        knowledge_base={"enabled": True, "document_ids": ["doc-1"], "top_k": 5, "mode": "tool"},
    )
    with patch("app.services.knowledge_service.assert_documents_ready"):
        with pytest.raises(AgentConfigValidationError) as exc:
            validate_agent_config(config, org_id="org-1")
    assert "function calling" in str(exc.value)
