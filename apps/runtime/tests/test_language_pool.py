"""Tests for language-keyed model pool deduplication."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.runtime.services.language_switch.pool import (
    configured_languages,
    resolve_language_stacks,
)


def _hi_stack(*, stt_provider: str, stt_model: str) -> dict:
    return {
        "stt_config": {
            "provider": stt_provider,
            "model": stt_model,
            "language": "hi",
        },
        "tts_config": {
            "provider": "cartesia",
            "model": "sonic-3.5",
            "language": "hi",
            "voice": "voice-a",
            "speed": 1,
            "volume": 1,
        },
        "llm_config": {"provider": "openai", "model": "gpt-4.1"},
    }


HI_MR_KN_AGENT = {
    "org_id": "52600c",
    "config": {
        "language": {"primary": "hi", "secondary": ["mr", "kn"]},
        "models": {
            "hi": _hi_stack(stt_provider="cartesia", stt_model="ink-whisper"),
            "mr": {
                **_hi_stack(stt_provider="bhashini", stt_model="bhashini/conformer"),
                "stt_config": {
                    "provider": "bhashini",
                    "model": "bhashini/conformer",
                    "language": "mr",
                },
                "tts_config": {
                    "provider": "cartesia",
                    "model": "sonic-3.5",
                    "language": "mr",
                    "voice": "voice-a",
                    "speed": 1,
                    "volume": 1,
                },
            },
            "kn": {
                **_hi_stack(stt_provider="deepgram", stt_model="nova-3-general"),
                "stt_config": {
                    "provider": "deepgram",
                    "model": "nova-3-general",
                    "language": "kn",
                },
                "tts_config": {
                    "provider": "cartesia",
                    "model": "sonic-3.5",
                    "language": "kn",
                    "voice": "voice-a",
                    "speed": 1,
                    "volume": 1,
                },
            },
        },
    },
}


def test_configured_languages_primary_and_secondary():
    langs = configured_languages(HI_MR_KN_AGENT)
    assert langs == ["hi", "mr", "kn"]


def test_resolve_language_stacks_keyed():
    stacks = resolve_language_stacks(HI_MR_KN_AGENT)
    assert set(stacks) == {"hi", "mr", "kn"}
    assert stacks["hi"]["stt_config"]["provider"] == "cartesia"


def test_resolve_language_stacks_legacy_flat():
    agent = {
        "config": {
            "language": {"primary": "en", "secondary": []},
            "models": _hi_stack(stt_provider="deepgram", stt_model="nova-3"),
        }
    }
    stacks = resolve_language_stacks(agent)
    assert stacks == {"en": agent["config"]["models"]}


@pytest.mark.asyncio
async def test_build_language_switchers_dedupes_services():
    from apps.runtime.services.language_switch.pool import build_language_switchers

    with (
        patch(
            "apps.runtime.services.language_switch.pool.merge_stack_with_auth",
            new=AsyncMock(side_effect=lambda stack, **_: stack),
        ),
        patch(
            "apps.runtime.services.language_switch.pool._create_service",
            side_effect=lambda kind, stack: MagicMock(name=f"{kind}-instance"),
        ) as create_service,
    ):
        stt_sw, tts_sw, llm_sw = await build_language_switchers(HI_MR_KN_AGENT)

    assert create_service.call_count == 5
    stt_calls = [call for call in create_service.call_args_list if call.args[0] == "stt"]
    tts_calls = [call for call in create_service.call_args_list if call.args[0] == "tts"]
    llm_calls = [call for call in create_service.call_args_list if call.args[0] == "llm"]
    assert len(stt_calls) == 3
    assert len(tts_calls) == 1
    assert len(llm_calls) == 1
    assert len(stt_sw.services) == 3
    assert len(tts_sw.services) == 1
    assert len(llm_sw.services) == 1
    assert stt_sw.active_language == "hi"
    assert tts_sw.active_language == "hi"


@pytest.mark.asyncio
async def test_build_language_switchers_same_provider_different_model():
    from apps.runtime.services.language_switch.pool import build_language_switchers

    agent = {
        "org_id": "org-1",
        "config": {
            "language": {"primary": "en", "secondary": ["te"]},
            "models": {
                "en": _hi_stack(stt_provider="deepgram", stt_model="nova-3"),
                "te": {
                    **_hi_stack(stt_provider="deepgram", stt_model="nova-2"),
                    "stt_config": {
                        "provider": "deepgram",
                        "model": "nova-2",
                        "language": "te",
                    },
                },
            },
        },
    }

    with (
        patch(
            "apps.runtime.services.language_switch.pool.merge_stack_with_auth",
            new=AsyncMock(side_effect=lambda stack, **_: stack),
        ),
        patch(
            "apps.runtime.services.language_switch.pool._create_service",
            side_effect=lambda kind, stack: MagicMock(name=kind),
        ) as create_service,
    ):
        stt_sw, _, _ = await build_language_switchers(agent)

    stt_calls = [call for call in create_service.call_args_list if call.args[0] == "stt"]
    assert len(stt_calls) == 2
    assert len(stt_sw.services) == 2
