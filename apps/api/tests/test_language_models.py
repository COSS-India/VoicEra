"""API-level tests for language_models agent configuration."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.models.schemas import AgentConfigPayload
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


def test_validate_hi_ml_language_models():
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
        }
    )
    validated = validate_agent_config(config)
    assert validated.language.primary == "hi"
    assert validated.language_models is not None
    assert validated.language_models["hi"].tts_config["voice"] == "alloy"
    assert validated.language_models["ml"].tts_config["voice"] == "shimmer"
    assert validated.models is not None
    assert validated.models.tts_config["voice"] == "alloy"


def test_validate_legacy_models_only():
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
    assert validated.language_models is not None
    assert set(validated.language_models) == {"en"}
    assert validated.models is not None


def test_language_models_missing_secondary_rejected_at_schema():
    with pytest.raises(ValidationError):
        AgentConfigPayload.model_validate(
            {
                "prompts": {
                    "system_prompt": "Helpful agent",
                    "greeting_message": "Namaste",
                },
                "language": {"primary": "hi", "secondary": ["ml"]},
                "language_models": {
                    "hi": _openai_stack(language="hi", voice="alloy"),
                },
            }
        )


def test_validate_rejects_empty_greeting():
    config = AgentConfigPayload.model_validate(
        {
            "prompts": {"system_prompt": "x", "greeting_message": "  "},
            "language": {"primary": "en", "secondary": []},
            "models": _openai_stack(language="en", voice="alloy"),
        }
    )
    with pytest.raises(AgentConfigValidationError):
        validate_agent_config(config)
