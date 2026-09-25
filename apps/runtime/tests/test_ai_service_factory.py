"""merge_models_with_auth skips stored auth for local (no-secret) providers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.providers import AgentConfig, create_llm_service
from apps.runtime.services.ai_service_factory import (
    _requires_stored_auth,
    build_ai_services,
    merge_models_with_auth,
)
from apps.runtime.services.language_switch import pool
from apps.runtime.services.language_switch.pool import resolve_language_stacks
from apps.runtime.services.pipecat.audio import caller_phone


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


def _stub_local_stt_tts(monkeypatch) -> None:
    """The local STT / TTS want a model server; each call gets a fresh stub."""
    from pipecat.processors.frame_processor import FrameProcessor

    monkeypatch.setattr(pool, "create_stt_service", lambda _cfg: FrameProcessor())
    monkeypatch.setattr(pool, "create_tts_service", lambda _cfg: FrameProcessor())


def _llm_for_a_call(monkeypatch, caller: str | None, send_caller_phone: bool):
    """``build_ai_services`` with the local STT / TTS builds stubbed out."""
    _stub_local_stt_tts(monkeypatch)
    client = MagicMock()
    client.get_provider_auth = AsyncMock(
        return_value={
            "base_url": "http://vllm.internal:8000/v1",
            "api_key": "sk-local",
            "endpoint_send_caller_phone": send_caller_phone,
        },
    )
    _, _, llm_switcher = asyncio.run(
        build_ai_services(_agent_on_a_connection({}), client, caller_phone=caller)
    )
    return llm_switcher.strategy.active_service


def test_the_callers_number_reaches_the_request(monkeypatch):
    llm = _llm_for_a_call(monkeypatch, "919900112233", send_caller_phone=True)
    params = llm.build_chat_completion_params({"messages": _HISTORY})
    assert params["metadata"] == {"caller_phone": "919900112233"}


def test_a_connection_without_the_toggle_sends_no_metadata(monkeypatch):
    llm = _llm_for_a_call(monkeypatch, "919900112233", send_caller_phone=False)
    assert "metadata" not in llm.build_chat_completion_params({"messages": _HISTORY})


def test_a_web_call_still_builds_and_sends_it_empty(monkeypatch):
    llm = _llm_for_a_call(monkeypatch, None, send_caller_phone=True)
    params = llm.build_chat_completion_params({"messages": _HISTORY})
    assert params["metadata"] == {"caller_phone": ""}


@pytest.mark.parametrize(
    ("call_log", "expected"),
    [
        ({"call_type": "inbound", "from_number": "+91 99001-12233", "to_number": "+918000000000"}, "919900112233"),
        ({"call_type": "outbound", "from_number": "+918000000000", "to_number": "+919900112233"}, "919900112233"),
        ({"call_type": "inbound", "from_number": "unknown"}, None),
        ({"call_type": "web", "from_number": "browser", "to_number": "agent"}, None),
        (None, None),
    ],
)
def test_caller_phone_is_the_remote_party_as_digits(call_log, expected):
    assert caller_phone(call_log) == expected


def test_merge_language_keyed_models_uses_primary_stack():
    client = MagicMock()
    client.get_provider_auth = AsyncMock(
        side_effect=lambda provider, org_id, connection_id=None: {
            "api_key": f"key-{provider}"
        },
    )
    agent = {
        "org_id": "org-1",
        "config": {
            "language": {"primary": "hi", "secondary": ["mr"]},
            "models": {
                "hi": {
                    "stt_config": {
                        "provider": "openai",
                        "model": "gpt-4o-transcribe",
                        "language": "hi",
                    },
                    "tts_config": {
                        "provider": "openai",
                        "model": "gpt-4o-mini-tts",
                        "language": "hi",
                        "voice": "alloy",
                    },
                    "llm_config": {"provider": "openai", "model": "gpt-4.1"},
                },
                "mr": {
                    "stt_config": {
                        "provider": "deepgram",
                        "model": "nova-3",
                        "language": "mr",
                    },
                    "tts_config": {
                        "provider": "openai",
                        "model": "gpt-4o-mini-tts",
                        "language": "mr",
                        "voice": "shimmer",
                    },
                    "llm_config": {"provider": "openai", "model": "gpt-4.1"},
                },
            },
        },
    }
    stacks = resolve_language_stacks(agent)
    assert set(stacks) == {"hi", "mr"}

    out = asyncio.run(merge_models_with_auth(agent, client=client))
    assert out["stt_config"]["provider"] == "openai"
    assert out["stt_config"]["api_key"] == "key-openai"
    client.get_provider_auth.assert_awaited_once_with(
        "openai", "org-1", connection_id=None
    )


def _stack_on(connection_id: str, language: str) -> dict:
    return {
        "stt_config": {
            "provider": "indic_nemotron",
            "model": "indic-nemotron-600m",
            "language": language,
        },
        "tts_config": {
            "provider": "indic_orpheus",
            "model": "orpheus-indic",
            "language": language,
            "voice": "Amit",
            "style": "news",
        },
        "llm_config": {
            "provider": "openai_compatible",
            "connection_id": connection_id,
            "model": "Qwen/Qwen3-8B-Instruct",
        },
    }


def _two_language_switchers(monkeypatch, caller: str | None = None):
    """``hi`` and ``mr`` serve the same model id from two different connections."""
    _stub_local_stt_tts(monkeypatch)
    endpoints = {
        "conn-hi": "http://hi.internal:8000/v1",
        "conn-mr": "http://mr.internal:8000/v1",
    }
    client = MagicMock()
    client.get_provider_auth = AsyncMock(
        side_effect=lambda provider, org_id, connection_id=None: {
            "base_url": endpoints[connection_id],
            "api_key": "sk-local",
            "endpoint_send_caller_phone": True,
        },
    )
    agent = {
        "org_id": "org-1",
        "config": {
            "language": {"primary": "hi", "secondary": ["mr"]},
            "models": {
                "hi": _stack_on("conn-hi", "hi"),
                "mr": _stack_on("conn-mr", "mr"),
            },
        },
    }
    _, _, llm_switcher = asyncio.run(
        build_ai_services(agent, client, caller_phone=caller)
    )
    return llm_switcher, client


def test_each_language_resolves_its_own_connection(monkeypatch):
    llm_switcher, client = _two_language_switchers(monkeypatch)
    assert client.get_provider_auth.await_count == 2
    client.get_provider_auth.assert_any_await(
        "openai_compatible", "org-1", connection_id="conn-hi"
    )
    client.get_provider_auth.assert_any_await(
        "openai_compatible", "org-1", connection_id="conn-mr"
    )
    # Same provider and model id, different endpoints: never pooled together.
    assert len(llm_switcher.services) == 2
    assert {str(llm._client.base_url) for llm in llm_switcher.services} == {
        "http://hi.internal:8000/v1/",
        "http://mr.internal:8000/v1/",
    }


def test_the_callers_number_reaches_every_language(monkeypatch):
    llm_switcher, _ = _two_language_switchers(monkeypatch, caller="919900112233")
    for llm in llm_switcher.services:
        params = llm.build_chat_completion_params({"messages": _HISTORY})
        assert params["metadata"] == {"caller_phone": "919900112233"}


def test_languages_on_one_connection_share_a_service_only_when_it_fits(monkeypatch):
    """History mode is fixed at build time; a switch cannot re-apply it."""
    _stub_local_stt_tts(monkeypatch)
    client = MagicMock()
    client.get_provider_auth = AsyncMock(
        return_value={"base_url": "http://vllm.internal:8000/v1", "api_key": "sk-local"},
    )

    def build(hi_llm_extra: dict):
        hi = _stack_on("conn-1", "hi")
        hi["llm_config"].update(hi_llm_extra)
        agent = {
            "org_id": "org-1",
            "config": {
                "language": {"primary": "en", "secondary": ["hi"]},
                "models": {"en": _stack_on("conn-1", "en"), "hi": hi},
            },
        }
        _, _, llm_switcher = asyncio.run(build_ai_services(agent, client))
        return llm_switcher

    # Only a delta-applied setting differs: one pooled service.
    assert len(build({"temperature": 0.2}).services) == 1
    # A build-time setting differs: each language gets its own.
    assert len(build({"history_mode": "current_turn"}).services) == 2
