"""merge_models_with_auth skips stored auth for local (no-secret) providers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from apps.providers import AgentConfig, create_llm_service
from apps.runtime.services.ai_service_factory import (
    _requires_stored_auth,
    merge_models_with_auth,
)


def test_local_providers_do_not_require_stored_auth():
    assert _requires_stored_auth("indic_nemotron") is False
    assert _requires_stored_auth("indic_orpheus") is False
    assert _requires_stored_auth("openai") is True
    assert _requires_stored_auth("deepgram") is True


def test_merge_skips_auth_fetch_for_local_stt_tts():
    client = MagicMock()
    client.get_provider_auth = AsyncMock(
        return_value={"api_key": "sk-test"},
    )
    agent = {
        "org_id": "org-1",
        "config": {
            "models": {
                "stt_config": {
                    "provider": "indic_nemotron",
                    "model": "indic-nemotron-600m",
                    "language": "hi",
                },
                "tts_config": {
                    "provider": "indic_orpheus",
                    "model": "orpheus-indic",
                    "language": "hi",
                    "voice": "Amit",
                    "style": "news",
                },
                "llm_config": {
                    "provider": "openai",
                    "model": "gpt-4.1",
                },
            }
        },
    }
    out = asyncio.run(merge_models_with_auth(agent, client=client))
    assert out["stt_config"]["provider"] == "indic_nemotron"
    assert "api_key" not in out["stt_config"]
    assert out["tts_config"]["provider"] == "indic_orpheus"
    assert out["llm_config"]["api_key"] == "sk-test"
    client.get_provider_auth.assert_awaited_once_with(
        "openai", "org-1", connection_id=None
    )


def test_merge_resolves_named_connection_for_openai_compatible():
    """The agent stores a reference; endpoint and key arrive at call setup."""
    client = MagicMock()
    client.get_provider_auth = AsyncMock(
        return_value={
            "base_url": "http://vllm.internal:8000/v1",
            "api_key": "sk-local",
        },
    )
    agent = {
        "org_id": "org-1",
        "config": {
            "models": {
                "stt_config": {
                    "provider": "indic_nemotron",
                    "model": "indic-nemotron-600m",
                    "language": "hi",
                },
                "tts_config": {
                    "provider": "indic_orpheus",
                    "model": "orpheus-indic",
                    "language": "hi",
                    "voice": "Amit",
                    "style": "news",
                },
                "llm_config": {
                    "provider": "openai_compatible",
                    "connection_id": "conn-42",
                    "model": "Qwen/Qwen3-8B-Instruct",
                },
            }
        },
    }
    out = asyncio.run(merge_models_with_auth(agent, client=client))
    assert out["llm_config"]["base_url"] == "http://vllm.internal:8000/v1"
    assert out["llm_config"]["api_key"] == "sk-local"
    client.get_provider_auth.assert_awaited_once_with(
        "openai_compatible", "org-1", connection_id="conn-42"
    )


def _agent_on_a_connection(llm_config: dict) -> dict:
    return {
        "org_id": "org-1",
        "config": {
            "models": {
                "stt_config": {
                    "provider": "indic_nemotron",
                    "model": "indic-nemotron-600m",
                    "language": "hi",
                },
                "tts_config": {
                    "provider": "indic_orpheus",
                    "model": "orpheus-indic",
                    "language": "hi",
                    "voice": "Amit",
                    "style": "news",
                },
                "llm_config": {
                    "provider": "openai_compatible",
                    "connection_id": "conn-42",
                    "model": "Qwen/Qwen3-8B-Instruct",
                    **llm_config,
                },
            }
        },
    }


def _llm_from(agent: dict, client: MagicMock):
    """Merge and build the LLM exactly as ``build_ai_services`` does.

    Only the LLM: the STT and TTS halves are local providers that want a model
    server on the network, which this seam has nothing to do with.
    """
    models = asyncio.run(merge_models_with_auth(agent, client=client))
    return create_llm_service(AgentConfig.model_validate(models))


def _built_llm(
    llm_config: dict,
    endpoint_history_mode: str = "full",
    endpoint_system_prompt_mode: str = "send",
):
    client = MagicMock()
    client.get_provider_auth = AsyncMock(
        return_value={
            "base_url": "http://vllm.internal:8000/v1",
            "api_key": "sk-local",
            "endpoint_history_mode": endpoint_history_mode,
            "endpoint_system_prompt_mode": endpoint_system_prompt_mode,
        },
    )
    return _llm_from(_agent_on_a_connection(llm_config), client)


def _sent_messages(llm, messages: list[dict]) -> list[dict]:
    return llm.build_chat_completion_params({"messages": list(messages)})["messages"]


_HISTORY = [
    {"role": "system", "content": "You are a helpful agent."},
    {"role": "user", "content": "first"},
    {"role": "assistant", "content": "answer"},
    {"role": "user", "content": "second"},
]


def test_the_endpoint_history_default_reaches_the_built_llm():
    """The whole seam: connection -> merged config -> service behaviour."""
    llm = _built_llm({}, endpoint_history_mode="current_turn")
    assert _sent_messages(llm, _HISTORY) == [_HISTORY[0], _HISTORY[3]]


def test_an_agent_that_sets_its_own_mode_ignores_the_endpoint():
    llm = _built_llm({"history_mode": "full"}, endpoint_history_mode="current_turn")
    assert _sent_messages(llm, _HISTORY) == _HISTORY

    llm = _built_llm({"history_mode": "current_turn"}, endpoint_history_mode="full")
    assert _sent_messages(llm, _HISTORY) == [_HISTORY[0], _HISTORY[3]]


def test_an_endpoint_that_builds_its_own_prompt_gets_one_bare_user_message():
    """The contract an endpoint with its own prompt and session state asks for."""
    llm = _built_llm(
        {},
        endpoint_history_mode="current_turn",
        endpoint_system_prompt_mode="omit",
    )
    assert _sent_messages(llm, _HISTORY) == [_HISTORY[3]]


def test_the_two_endpoint_modes_are_set_independently():
    llm = _built_llm({}, endpoint_system_prompt_mode="omit")
    assert _sent_messages(llm, _HISTORY) == _HISTORY[1:]


def test_a_connection_that_predates_the_setting_keeps_the_full_conversation():
    """Older endpoints resolve without the key; the agent still gets history."""
    client = MagicMock()
    client.get_provider_auth = AsyncMock(
        return_value={
            "base_url": "http://vllm.internal:8000/v1",
            "api_key": "sk-local",
        },
    )
    llm = _llm_from(_agent_on_a_connection({}), client)
    assert _sent_messages(llm, _HISTORY) == _HISTORY
