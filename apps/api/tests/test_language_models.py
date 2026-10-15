"""API-level tests for language-keyed agent ``models`` configuration."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.models.schemas import AgentConfigPayload, AgentCreateRequest
from app.services.agent_config_validation import (
    AgentConfigValidationError,
    validate_agent_config,
)


def _openai_stack(*, language: str, voice: str) -> dict[str, Any]:
    return {
        "stt_config": {
            "provider": "openai",
            "model": "gpt-4o-transcribe",
            "language": language,
        },
        "tts_config": {
            "provider": "openai",
            "model": "gpt-4o-mini-tts",
            "voice": voice,
            "language": language,
        },
        "llm_config": {"provider": "openai", "model": "gpt-4o-mini"},
    }


def test_validate_hi_ml_models():
    config = AgentConfigPayload.model_validate(
        {
            "prompts": {
                "system_prompt": "Helpful agent",
                "greeting_message": "Namaste",
            },
            "language": {"primary": "hi", "secondary": ["ml"]},
            "models": {
                "hi": _openai_stack(language="hi", voice="alloy"),
                "ml": _openai_stack(language="ml", voice="shimmer"),
            },
        }
    )
    validated = validate_agent_config(config)
    assert validated.language.primary == "hi"
    assert set(validated.models) == {"hi", "ml"}
    assert validated.models["hi"].tts_config["voice"] == "alloy"
    assert validated.models["ml"].tts_config["voice"] == "shimmer"
    dumped = validated.model_dump(mode="python")
    assert "language_models" not in dumped
    assert "stt_config" not in dumped["models"]


def test_validate_legacy_flat_models_only():
    config = AgentConfigPayload.model_validate(
        {
            "prompts": {
                "system_prompt": "Helpful agent",
                "greeting_message": "Hello",
            },
            "language": {"primary": "en", "secondary": []},
            "models": _openai_stack(language="en", voice="alloy"),
        }
    )
    validated = validate_agent_config(config)
    assert set(validated.models) == {"en"}
    assert validated.models["en"].tts_config["voice"] == "alloy"


def test_legacy_language_models_folded_into_models():
    config = AgentConfigPayload.model_validate(
        {
            "prompts": {
                "system_prompt": "Helpful agent",
                "greeting_message": "Namaste",
            },
            "language": {"primary": "hi", "secondary": ["ml"]},
            "language_models": {
                "hi": _openai_stack(language="hi", voice="alloy"),
                "ml": _openai_stack(language="ml", voice="shimmer"),
            },
            # Flat primary alias from older documents — ignored when the map exists.
            "models": _openai_stack(language="hi", voice="alloy"),
        }
    )
    validated = validate_agent_config(config)
    assert set(validated.models) == {"hi", "ml"}
    dumped = validated.model_dump(mode="python")
    assert "language_models" not in dumped


def test_models_missing_secondary_rejected_at_schema():
    with pytest.raises(ValidationError):
        AgentConfigPayload.model_validate(
            {
                "prompts": {
                    "system_prompt": "Helpful agent",
                    "greeting_message": "Namaste",
                },
                "language": {"primary": "hi", "secondary": ["ml"]},
                "models": {
                    "hi": _openai_stack(language="hi", voice="alloy"),
                },
            }
        )


def test_create_example_uses_language_keyed_models():
    extras = AgentCreateRequest.model_config.get("json_schema_extra") or {}
    example = extras["examples"][0]
    payload = AgentCreateRequest.model_validate(example)
    assert "language_models" not in example["config"]
    assert "en" in payload.config.models
    assert payload.config.models["en"].stt_config["provider"] == "deepgram"


def test_persisted_configs_omit_kind_and_name():
    config = AgentConfigPayload.model_validate(
        {
            "prompts": {
                "system_prompt": "Helpful agent",
                "greeting_message": "Hello",
            },
            "language": {"primary": "en", "secondary": []},
            "models": {"en": _openai_stack(language="en", voice="alloy")},
        }
    )
    validated = validate_agent_config(config)
    stt = validated.models["en"].stt_config
    assert "kind" not in stt
    assert "name" not in stt
    assert stt["provider"] == "openai"


def test_validate_rejects_empty_greeting():
    config = AgentConfigPayload.model_validate(
        {
            "prompts": {"system_prompt": "x", "greeting_message": "  "},
            "language": {"primary": "en", "secondary": []},
            "models": {"en": _openai_stack(language="en", voice="alloy")},
        }
    )
    with pytest.raises(AgentConfigValidationError):
        validate_agent_config(config)
