"""Tests for mid-call language switching (config + LanguageSwitcher)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from apps.runtime.services.ai_service_factory import (
    resolve_language_models,
)
from apps.runtime.services.pipecat.language_switch import (
    LanguageSwitcher,
    build_language_switcher,
    configure_language_switching,
    extract_tts_runtime_settings,
)


def _stack(
    *,
    language: str,
    voice: str,
    stt_provider: str = "cartesia",
    tts_provider: str = "cartesia",
    llm_model: str = "gpt-4.1",
) -> dict[str, Any]:
    return {
        "stt_config": {
            "provider": stt_provider,
            "model": "ink-whisper",
            "language": language,
        },
        "tts_config": {
            "provider": tts_provider,
            "model": "sonic-3.5",
            "language": language,
            "voice": voice,
            "speed": 1.0,
            "volume": 1.0,
        },
        "llm_config": {
            "provider": "openai",
            "model": llm_model,
        },
    }


HI_VOICE = "hindi-voice-id"
ML_VOICE = "malayalam-voice-id"


def _hi_ml_agent() -> dict[str, Any]:
    return {
        "agent_id": "agent-1",
        "org_id": "org-1",
        "config": {
            "language": {"primary": "hi", "secondary": ["ml"]},
            "language_models": {
                "hi": _stack(language="hi", voice=HI_VOICE),
                "ml": _stack(language="ml", voice=ML_VOICE),
            },
            "models": _stack(language="hi", voice=HI_VOICE),
        },
    }


def test_resolve_language_models_prefers_language_models():
    config = _hi_ml_agent()["config"]
    resolved = resolve_language_models(config)
    assert set(resolved) == {"hi", "ml"}
    assert resolved["hi"]["tts_config"]["voice"] == HI_VOICE
    assert resolved["ml"]["tts_config"]["voice"] == ML_VOICE


def test_resolve_language_models_legacy_models_only():
    config = {
        "language": {"primary": "hi", "secondary": ["kn"]},
        "models": _stack(language="hi", voice=HI_VOICE),
    }
    resolved = resolve_language_models(config)
    assert list(resolved.keys()) == ["hi"]
    assert resolved["hi"]["tts_config"]["voice"] == HI_VOICE


def test_extract_tts_runtime_settings_keeps_voice():
    settings = extract_tts_runtime_settings(
        _stack(language="ml", voice=ML_VOICE)["tts_config"]
    )
    assert settings["language"] == "ml"
    assert settings["voice"] == ML_VOICE
    assert settings["model"] == "sonic-3.5"
    assert "provider" not in settings
    assert "api_key" not in settings


def test_build_language_switcher_requires_two_configured_languages():
    agent = {
        "config": {
            "language": {"primary": "hi", "secondary": []},
            "language_models": {"hi": _stack(language="hi", voice=HI_VOICE)},
        }
    }
    assert build_language_switcher(agent, llm=MagicMock()) is None


def test_initialization_uses_primary_language_stack():
    agent = _hi_ml_agent()
    switcher = build_language_switcher(agent, llm=MagicMock())
    assert switcher is not None
    assert switcher.active_language == "hi"
    assert switcher.stack_for("hi")["tts_config"]["voice"] == HI_VOICE


def test_switch_language_to_ml_and_back_restores_hindi_voice():
    llm = MagicMock()
    llm.push_frame = AsyncMock()
    llm._update_settings = AsyncMock()

    switcher = LanguageSwitcher(
        language_models=resolve_language_models(_hi_ml_agent()["config"]),
        active_language="hi",
        llm=llm,
        allowed_languages=["hi", "ml"],
    )

    result = asyncio.run(switcher.switch("ml"))
    assert result["status"] == "ok"
    assert result["active_language"] == "ml"
    assert result["voice"] == ML_VOICE
    assert switcher.active_language == "ml"
    assert llm.push_frame.await_count >= 2

    result_back = asyncio.run(switcher.switch("hi"))
    assert result_back["status"] == "ok"
    assert result_back["active_language"] == "hi"
    assert result_back["voice"] == HI_VOICE
    assert switcher.active_language == "hi"


def test_switch_language_invalid_keeps_current():
    llm = MagicMock()
    llm.push_frame = AsyncMock()
    switcher = LanguageSwitcher(
        language_models=resolve_language_models(_hi_ml_agent()["config"]),
        active_language="hi",
        llm=llm,
        allowed_languages=["hi", "ml"],
    )

    result = asyncio.run(switcher.switch("ta"))
    assert result["status"] == "error"
    assert switcher.active_language == "hi"
    llm.push_frame.assert_not_awaited()


def test_multiple_switches_hi_ml_hi_ml():
    llm = MagicMock()
    llm.push_frame = AsyncMock()
    llm._update_settings = AsyncMock()
    switcher = LanguageSwitcher(
        language_models=resolve_language_models(_hi_ml_agent()["config"]),
        active_language="hi",
        llm=llm,
        allowed_languages=["hi", "ml"],
    )

    voices = []
    for lang in ("ml", "hi", "ml"):
        result = asyncio.run(switcher.switch(lang))
        assert result["status"] == "ok"
        assert result["active_language"] == lang
        voices.append(result["voice"])

    assert voices == [ML_VOICE, HI_VOICE, ML_VOICE]
    assert switcher.active_language == "ml"


def test_provider_mismatch_rejected():
    llm = MagicMock()
    llm.push_frame = AsyncMock()
    stacks = {
        "hi": _stack(language="hi", voice=HI_VOICE, tts_provider="cartesia"),
        "ml": _stack(language="ml", voice=ML_VOICE, tts_provider="elevenlabs"),
    }
    switcher = LanguageSwitcher(
        language_models=stacks,
        active_language="hi",
        llm=llm,
        allowed_languages=["hi", "ml"],
    )
    result = asyncio.run(switcher.switch("ml"))
    assert result["status"] == "error"
    assert "provider" in result["error"]
    assert switcher.active_language == "hi"
    llm.push_frame.assert_not_awaited()


def test_configure_language_switching_registers_tool():
    from pipecat.processors.aggregators.llm_context import LLMContext, NOT_GIVEN

    context = LLMContext([])
    assert context.tools is NOT_GIVEN
    switcher = configure_language_switching(
        _hi_ml_agent(),
        context=context,
        llm=MagicMock(),
    )
    assert switcher is not None
    names = {tool.name for tool in context.tools.standard_tools}
    assert "switch_language" in names


def test_api_schema_hi_ml_language_models_validates():
    """AgentConfigPayload accepts Hindi + Malayalam language_models."""
    import sys
    from pathlib import Path

    api_root = Path(__file__).resolve().parents[2] / "api"
    sys.path.insert(0, str(api_root))
    from app.models.schemas import AgentConfigPayload

    payload = AgentConfigPayload.model_validate(
        {
            "prompts": {
                "system_prompt": "You are helpful.",
                "greeting_message": "Namaste",
            },
            "language": {"primary": "hi", "secondary": ["ml"]},
            "language_models": {
                "hi": _stack(language="hi", voice=HI_VOICE),
                "ml": _stack(language="ml", voice=ML_VOICE),
            },
        }
    )
    assert payload.models is not None
    assert payload.models.tts_config["voice"] == HI_VOICE
    assert payload.language_models is not None
    assert payload.language_models["ml"].tts_config["voice"] == ML_VOICE


def test_api_schema_legacy_models_still_accepted():
    import sys
    from pathlib import Path

    api_root = Path(__file__).resolve().parents[2] / "api"
    sys.path.insert(0, str(api_root))
    from app.models.schemas import AgentConfigPayload

    payload = AgentConfigPayload.model_validate(
        {
            "prompts": {
                "system_prompt": "You are helpful.",
                "greeting_message": "Hello",
            },
            "language": {"primary": "en", "secondary": ["hi"]},
            "models": _stack(language="en", voice="en-voice"),
        }
    )
    assert payload.language_models is not None
    assert set(payload.language_models) == {"en"}


def test_api_schema_language_models_requires_secondary_entries():
    import sys
    from pathlib import Path

    api_root = Path(__file__).resolve().parents[2] / "api"
    sys.path.insert(0, str(api_root))
    from app.models.schemas import AgentConfigPayload

    with pytest.raises(ValidationError):
        AgentConfigPayload.model_validate(
            {
                "prompts": {
                    "system_prompt": "You are helpful.",
                    "greeting_message": "Namaste",
                },
                "language": {"primary": "hi", "secondary": ["ml"]},
                "language_models": {
                    "hi": _stack(language="hi", voice=HI_VOICE),
                },
            }
        )
