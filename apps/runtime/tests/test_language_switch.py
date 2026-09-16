"""Tests for mid-call language switching (frame + LanguageSwitchProcessor)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from pipecat.frames.frames import STTUpdateSettingsFrame, TTSUpdateSettingsFrame
from pipecat.processors.aggregators.llm_context import LLMContext, NOT_GIVEN
from pipecat.processors.frame_processor import FrameDirection
from pydantic import ValidationError

from apps.runtime.services.ai_service_factory import (
    resolve_language_models,
)
from apps.runtime.services.pipecat.frames import LanguageSwitchFrame
from apps.runtime.services.pipecat.language_switch import (
    LanguageSwitchProcessor,
    build_language_switcher,
    extract_tts_runtime_settings,
    register_language_switching_tool,
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


def _processor(
    *,
    stacks: dict[str, dict[str, Any]] | None = None,
    allowed: list[str] | None = None,
    llm: Any | None = None,
) -> LanguageSwitchProcessor:
    llm = llm or MagicMock()
    llm.push_frame = AsyncMock()
    llm.broadcast_frame = AsyncMock()
    llm._update_settings = AsyncMock()
    processor = LanguageSwitchProcessor(
        language_models=stacks or resolve_language_models(_hi_ml_agent()["config"]),
        active_language="hi",
        llm=llm,
        allowed_languages=allowed or ["hi", "ml"],
    )
    processor.push_frame = AsyncMock()
    return processor


def _pushed_frames(processor: LanguageSwitchProcessor) -> list[Any]:
    return [call.args[0] for call in processor.push_frame.await_args_list]


def _function_params(llm: Any) -> Any:
    params = MagicMock()
    params.llm = llm
    params.result_callback = AsyncMock()
    return params


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
    processor = build_language_switcher(agent, llm=MagicMock())
    assert processor is not None
    assert processor.active_language == "hi"
    assert processor.stack_for("hi")["tts_config"]["voice"] == HI_VOICE


def test_switch_language_tool_emits_frame_not_updates():
    llm = MagicMock()
    llm.broadcast_frame = AsyncMock()
    llm.push_frame = AsyncMock()
    llm._update_settings = AsyncMock()
    context = LLMContext([])
    processor = register_language_switching_tool(_hi_ml_agent(), context=context, llm=llm)
    assert processor is not None
    processor.push_frame = AsyncMock()

    params = _function_params(llm)
    asyncio.run(processor.switch_language(params, "ml"))

    llm.broadcast_frame.assert_awaited_once()
    assert llm.broadcast_frame.await_args.args[0] is LanguageSwitchFrame
    assert llm.broadcast_frame.await_args.kwargs["language"] == "ml"
    llm._update_settings.assert_not_awaited()
    processor.push_frame.assert_not_awaited()
    for call in llm.push_frame.await_args_list:
        frame = call.args[0]
        assert not isinstance(frame, (STTUpdateSettingsFrame, TTSUpdateSettingsFrame))
        assert not isinstance(frame, LanguageSwitchFrame)
    result = params.result_callback.await_args.args[0]
    assert result["status"] == "ok"
    assert result["requested_language"] == "ml"
    assert processor.active_language == "hi"


def test_switch_language_tool_rejects_invalid_without_frame():
    llm = MagicMock()
    llm.broadcast_frame = AsyncMock()
    llm._update_settings = AsyncMock()
    processor = register_language_switching_tool(
        _hi_ml_agent(), context=LLMContext([]), llm=llm
    )
    assert processor is not None

    params = _function_params(llm)
    asyncio.run(processor.switch_language(params, "xyz"))

    llm.broadcast_frame.assert_not_awaited()
    llm._update_settings.assert_not_awaited()
    result = params.result_callback.await_args.args[0]
    assert result["status"] == "error"
    assert processor.active_language == "hi"


def test_switch_language_tool_rejects_empty_without_frame():
    llm = MagicMock()
    llm.broadcast_frame = AsyncMock()
    processor = register_language_switching_tool(
        _hi_ml_agent(), context=LLMContext([]), llm=llm
    )
    assert processor is not None

    params = _function_params(llm)
    asyncio.run(processor.switch_language(params, "  "))

    llm.broadcast_frame.assert_not_awaited()
    result = params.result_callback.await_args.args[0]
    assert result["status"] == "error"


def test_switch_language_tool_emits_frame_for_configured_language_even_if_providers_differ():
    """The tool only validates language availability; provider checks are the processor's."""
    llm = MagicMock()
    llm.broadcast_frame = AsyncMock()
    llm.push_frame = AsyncMock()
    llm._update_settings = AsyncMock()
    stacks = {
        "hi": _stack(language="hi", voice=HI_VOICE, tts_provider="cartesia"),
        "ml": _stack(language="ml", voice=ML_VOICE, tts_provider="elevenlabs"),
    }
    processor = register_language_switching_tool(
        _hi_ml_agent(),
        context=LLMContext([]),
        llm=llm,
        language_models=stacks,
    )
    assert processor is not None
    processor.push_frame = AsyncMock()

    params = _function_params(llm)
    asyncio.run(processor.switch_language(params, "ml"))

    llm.broadcast_frame.assert_awaited_once()
    assert llm.broadcast_frame.await_args.kwargs["language"] == "ml"
    llm._update_settings.assert_not_awaited()
    processor.push_frame.assert_not_awaited()
    assert processor.active_language == "hi"


def test_processor_handles_language_switch_frame():
    processor = _processor()
    llm = processor.llm

    asyncio.run(
        processor.process_frame(
            LanguageSwitchFrame(language="ml"), FrameDirection.DOWNSTREAM
        )
    )

    assert processor.active_language == "ml"
    frames = _pushed_frames(processor)
    assert any(isinstance(frame, STTUpdateSettingsFrame) for frame in frames)
    tts_frames = [f for f in frames if isinstance(f, TTSUpdateSettingsFrame)]
    assert tts_frames
    assert tts_frames[0].delta.voice == ML_VOICE
    llm._update_settings.assert_awaited()
    assert not any(isinstance(frame, LanguageSwitchFrame) for frame in frames)

    directions = {
        type(call.args[0]): call.args[1] for call in processor.push_frame.await_args_list
    }
    assert directions[STTUpdateSettingsFrame] == FrameDirection.UPSTREAM
    assert directions[TTSUpdateSettingsFrame] == FrameDirection.DOWNSTREAM


def test_processor_handles_upstream_language_switch_frame():
    processor = _processor()
    asyncio.run(
        processor.process_frame(
            LanguageSwitchFrame(language="ml"), FrameDirection.UPSTREAM
        )
    )
    assert processor.active_language == "ml"
    assert any(
        isinstance(frame, STTUpdateSettingsFrame) for frame in _pushed_frames(processor)
    )


def test_invalid_language_frame_does_not_change_settings():
    processor = _processor()
    llm = processor.llm

    asyncio.run(
        processor.process_frame(
            LanguageSwitchFrame(language="xyz"), FrameDirection.DOWNSTREAM
        )
    )

    assert processor.active_language == "hi"
    processor.push_frame.assert_not_awaited()
    llm._update_settings.assert_not_awaited()


def test_same_language_frame_is_noop():
    processor = _processor()
    processor.active_language = "ml"

    asyncio.run(
        processor.process_frame(
            LanguageSwitchFrame(language="ml"), FrameDirection.DOWNSTREAM
        )
    )

    assert processor.active_language == "ml"
    processor.push_frame.assert_not_awaited()
    processor.llm._update_settings.assert_not_awaited()


def test_active_language_updates_only_after_successful_updates():
    processor = _processor()
    processor.push_frame = AsyncMock(side_effect=RuntimeError("stt failed"))

    result = asyncio.run(processor.switch("ml"))

    assert result["status"] == "error"
    assert processor.active_language == "hi"
    processor.llm._update_settings.assert_not_awaited()


def test_switch_language_to_ml_and_back_restores_hindi_voice():
    processor = _processor()

    asyncio.run(
        processor.process_frame(
            LanguageSwitchFrame(language="ml"), FrameDirection.DOWNSTREAM
        )
    )
    assert processor.active_language == "ml"
    tts_frames = [
        f for f in _pushed_frames(processor) if isinstance(f, TTSUpdateSettingsFrame)
    ]
    assert tts_frames[-1].delta.voice == ML_VOICE

    result_back = asyncio.run(processor.switch("hi"))
    assert result_back["status"] == "ok"
    assert result_back["active_language"] == "hi"
    assert result_back["voice"] == HI_VOICE
    assert processor.active_language == "hi"
    tts_frames = [
        f for f in _pushed_frames(processor) if isinstance(f, TTSUpdateSettingsFrame)
    ]
    assert tts_frames[-1].delta.voice == HI_VOICE


def test_multiple_switches_hi_ml_hi_ml():
    processor = _processor()

    voices = []
    for lang in ("ml", "hi", "ml"):
        result = asyncio.run(processor.switch(lang))
        assert result["status"] == "ok"
        assert result["active_language"] == lang
        voices.append(result["voice"])

    assert voices == [ML_VOICE, HI_VOICE, ML_VOICE]
    assert processor.active_language == "ml"


def test_provider_mismatch_rejected():
    stacks = {
        "hi": _stack(language="hi", voice=HI_VOICE, tts_provider="cartesia"),
        "ml": _stack(language="ml", voice=ML_VOICE, tts_provider="elevenlabs"),
    }
    processor = _processor(stacks=stacks)

    asyncio.run(
        processor.process_frame(
            LanguageSwitchFrame(language="ml"), FrameDirection.DOWNSTREAM
        )
    )
    assert processor.active_language == "hi"
    processor.push_frame.assert_not_awaited()
    processor.llm._update_settings.assert_not_awaited()


def test_register_language_switching_tool_registers_tool():
    context = LLMContext([])
    assert context.tools is NOT_GIVEN
    processor = register_language_switching_tool(
        _hi_ml_agent(),
        context=context,
        llm=MagicMock(),
    )
    assert processor is not None
    names = {tool.name for tool in context.tools.standard_tools}
    assert "switch_language" in names


def _agent_config_payload():
    import sys
    from pathlib import Path

    api_root = Path(__file__).resolve().parents[2] / "api"
    sys.path.insert(0, str(api_root))
    try:
        from app.models.schemas import AgentConfigPayload
    except Exception as exc:
        pytest.skip(f"API schemas are not importable here: {exc}")
    return AgentConfigPayload


def test_api_schema_hi_ml_language_models_validates():
    """AgentConfigPayload accepts Hindi + Malayalam language_models."""
    AgentConfigPayload = _agent_config_payload()

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
    AgentConfigPayload = _agent_config_payload()

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
    AgentConfigPayload = _agent_config_payload()

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
