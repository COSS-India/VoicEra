"""Unit tests for validation, placeholder stripping and config resolution."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.services.tts_preview_service import (
    TtsPreviewError,
    TtsPreviewErrorReason,
    resolve_config,
    strip_placeholders,
    validate_request,
)


def _run(coro):
    return asyncio.run(coro)


def test_strip_placeholders_removes_braces_and_collapses_space_before_punctuation():
    assert strip_placeholders("Namaste {{name}}, welcome!") == "Namaste, welcome!"


def test_strip_placeholders_collapses_double_spaces():
    assert strip_placeholders("Hello  {{name}}  there") == "Hello there"


def test_empty_text_after_stripping_returns_empty_text_reason():
    with pytest.raises(TtsPreviewError) as exc_info:
        validate_request({"provider": "sarvam", "model": "bulbul:v3", "voice": "shubh"}, "hi", "")
    assert exc_info.value.reason == TtsPreviewErrorReason.EMPTY_TEXT


def test_oversized_text_returns_oversized_reason():
    with patch("app.services.tts_preview_service.settings") as mock_settings:
        mock_settings.TTS_PREVIEW_MAX_CHARS = 5
        with pytest.raises(TtsPreviewError) as exc_info:
            validate_request(
                {"provider": "sarvam", "model": "bulbul:v3", "voice": "shubh"}, "hi", "too long text"
            )
    assert exc_info.value.reason == TtsPreviewErrorReason.OVERSIZED


def test_invalid_config_returns_invalid_config_reason():
    with pytest.raises(TtsPreviewError) as exc_info:
        validate_request({"provider": "not-a-real-provider"}, "hi", "hello")
    assert exc_info.value.reason == TtsPreviewErrorReason.INVALID_CONFIG


def test_provider_without_preview_adapter_returns_unsupported_voice_reason():
    with pytest.raises(TtsPreviewError) as exc_info:
        validate_request(
            {"provider": "elevenlabs", "model": "eleven_v3", "voice": "some-voice"},
            "en",
            "hello",
        )
    assert exc_info.value.reason == TtsPreviewErrorReason.UNSUPPORTED_VOICE


def test_valid_sarvam_config_passes_validation():
    validated = validate_request(
        {"provider": "sarvam", "model": "bulbul:v3", "voice": "shubh"}, "hi", "hello"
    )
    assert validated["provider"] == "sarvam"


def test_resolve_config_raises_not_configured_when_provider_missing():
    with patch(
        "app.services.tts_preview_service.auth_service.list_configured_providers",
        return_value=[],
    ):
        with pytest.raises(TtsPreviewError) as exc_info:
            _run(resolve_config("org-1", {"provider": "sarvam", "model": "bulbul:v3", "voice": "shubh"}))
    assert exc_info.value.reason == TtsPreviewErrorReason.NOT_CONFIGURED


def test_resolve_config_builds_typed_config_from_blob_and_auth():
    with (
        patch(
            "app.services.tts_preview_service.auth_service.list_configured_providers",
            return_value=["sarvam"],
        ),
        patch(
            "app.services.tts_preview_service.auth_service.get_provider_auth",
            return_value={"auth": {"api_key": "secret-key"}},
        ),
    ):
        cfg = _run(
            resolve_config(
                "org-1", {"provider": "sarvam", "model": "bulbul:v3", "voice": "shubh"}
            )
        )
    assert cfg.api_key == "secret-key"
    assert cfg.voice == "shubh"
