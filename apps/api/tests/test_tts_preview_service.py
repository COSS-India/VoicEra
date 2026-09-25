"""Unit tests for validation, placeholder stripping and config resolution."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from apps.providers.preview import PreviewProviderError

from app.services.tts_preview_service import (
    TtsPreviewError,
    TtsPreviewErrorReason,
    _voice_is_supported,
    generate_preview,
    resolve_config,
    strip_placeholders,
    validate_request,
)


def _patch_configured_sarvam():
    return (
        patch(
            "app.services.tts_preview_service.auth_service.list_configured_providers",
            return_value=["sarvam"],
        ),
        patch(
            "app.services.tts_preview_service.auth_service.get_provider_auth",
            return_value={"auth": {"api_key": "secret-key"}},
        ),
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


def test_voice_is_supported_true_for_sarvam_custom_voice():
    assert _voice_is_supported(
        {"provider": "sarvam", "model": "bulbul:v3", "voice": "totally-custom-voice"}, "hi"
    )


def test_voice_is_supported_false_for_openai_voice_not_in_closed_list():
    assert not _voice_is_supported(
        {"provider": "openai", "model": "gpt-4o-mini-tts", "voice": "not-a-real-voice"}, "en"
    )


def test_voice_is_supported_true_for_openai_voice_in_closed_list():
    assert _voice_is_supported(
        {"provider": "openai", "model": "gpt-4o-mini-tts", "voice": "alloy"}, "en"
    )


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


def test_generate_preview_returns_audio_on_success():
    patches = _patch_configured_sarvam()
    with patches[0], patches[1], patch(
        "app.services.tts_preview_service.synthesize_preview",
        new_callable=AsyncMock,
        return_value=b"RIFF....WAVEfmt ",
    ):
        audio = _run(
            generate_preview(
                "org-1",
                {"provider": "sarvam", "model": "bulbul:v3", "voice": "shubh"},
                "hi",
                "Namaste {{name}}",
            )
        )
    assert audio == b"RIFF....WAVEfmt "


def test_generate_preview_strips_placeholders_before_synthesis():
    patches = _patch_configured_sarvam()
    with patches[0], patches[1], patch(
        "app.services.tts_preview_service.synthesize_preview",
        new_callable=AsyncMock,
        return_value=b"audio",
    ) as mock_synthesize:
        _run(
            generate_preview(
                "org-1",
                {"provider": "sarvam", "model": "bulbul:v3", "voice": "shubh"},
                "hi",
                "Namaste {{name}}, welcome!",
            )
        )
    assert mock_synthesize.call_args.args[2] == "Namaste, welcome!"


def test_generate_preview_maps_timeout_to_timeout_reason():
    async def _hang(*_args, **_kwargs):
        await asyncio.sleep(10)

    patches = _patch_configured_sarvam()
    with (
        patches[0],
        patches[1],
        patch("app.services.tts_preview_service.settings") as mock_settings,
        patch("app.services.tts_preview_service.synthesize_preview", side_effect=_hang),
    ):
        mock_settings.TTS_PREVIEW_MAX_CHARS = 300
        mock_settings.TTS_PREVIEW_TIMEOUT_S = 0.01
        with pytest.raises(TtsPreviewError) as exc_info:
            _run(
                generate_preview(
                    "org-1",
                    {"provider": "sarvam", "model": "bulbul:v3", "voice": "shubh"},
                    "hi",
                    "hello",
                )
            )
    assert exc_info.value.reason == TtsPreviewErrorReason.TIMEOUT


def test_generate_preview_maps_provider_error_to_upstream_reason():
    patches = _patch_configured_sarvam()
    with patches[0], patches[1], patch(
        "app.services.tts_preview_service.synthesize_preview",
        new_callable=AsyncMock,
        side_effect=PreviewProviderError("vendor exploded"),
    ):
        with pytest.raises(TtsPreviewError) as exc_info:
            _run(
                generate_preview(
                    "org-1",
                    {"provider": "sarvam", "model": "bulbul:v3", "voice": "shubh"},
                    "hi",
                    "hello",
                )
            )
    assert exc_info.value.reason == TtsPreviewErrorReason.UPSTREAM
