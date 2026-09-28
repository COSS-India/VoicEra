"""merge_models_with_auth skips stored auth for local (no-secret) providers."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from apps.runtime.services.ai_service_factory import (
    _requires_stored_auth,
    merge_models_with_auth,
)
from apps.runtime.services.language_switch.pool import resolve_language_stacks


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
    client.get_provider_auth.assert_awaited_once_with("openai", "org-1")


def test_merge_language_keyed_models_uses_primary_stack():
    client = MagicMock()
    client.get_provider_auth = AsyncMock(
        side_effect=lambda provider, org_id: {"api_key": f"key-{provider}"},
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
    client.get_provider_auth.assert_awaited_once_with("openai", "org-1")


def _bluedots_agent() -> dict:
    return {
        "org_id": "org-1",
        "config": {
            "language": {"primary": "en", "secondary": []},
            "models": {
                "en": {
                    "stt_config": {
                        "provider": "indic_nemotron",
                        "model": "indic-nemotron-600m",
                        "language": "en",
                    },
                    "tts_config": {
                        "provider": "indic_orpheus",
                        "model": "orpheus-indic",
                        "language": "en",
                        "voice": "Amit",
                        "style": "news",
                    },
                    "llm_config": {
                        "provider": "bluedots",
                        "model": "bluedots",
                    },
                },
            },
        },
    }


def _llm_for_bluedots_call(monkeypatch, caller: str | None):
    pytest.importorskip("pipecat")
    from pipecat.processors.frame_processor import FrameProcessor

    from apps.runtime.services.ai_service_factory import build_ai_services
    from apps.runtime.services.language_switch import pool

    monkeypatch.setattr(pool, "create_stt_service", lambda _cfg: FrameProcessor())
    monkeypatch.setattr(pool, "create_tts_service", lambda _cfg: FrameProcessor())

    client = MagicMock()
    client.get_provider_auth = AsyncMock(
        return_value={
            "api_key": "sk-bluedots",
            "base_url": "http://bluedots.internal:8000/v1",
        }
    )
    _, _, llm_switcher = asyncio.run(
        build_ai_services(_bluedots_agent(), client, caller_phone=caller)
    )
    return llm_switcher.strategy.active_service


def test_bluedots_caller_phone_reaches_the_request(monkeypatch):
    llm = _llm_for_bluedots_call(monkeypatch, "919900112233")
    params = llm.build_chat_completion_params(
        {"messages": [{"role": "user", "content": "hi"}]}
    )
    assert params["metadata"] == {"caller_phone": "919900112233"}


def test_bluedots_web_call_sends_empty_caller_phone(monkeypatch):
    llm = _llm_for_bluedots_call(monkeypatch, None)
    params = llm.build_chat_completion_params(
        {"messages": [{"role": "user", "content": "hi"}]}
    )
    assert params["metadata"] == {"caller_phone": ""}
