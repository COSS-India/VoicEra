"""Unit tests for validation, placeholder stripping and config resolution."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from minio.error import S3Error

from apps.providers.preview import PreviewProviderError

from app.services.tts_preview_service import (
    TtsPreviewError,
    TtsPreviewErrorReason,
    _voice_is_supported,
    build_cache_key,
    check_rate_limit,
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


def _no_such_key() -> S3Error:
    return S3Error(MagicMock(), "NoSuchKey", "missing", "key", "req", "host")


@pytest.fixture(autouse=True)
def storage():
    """Stub MinIO with an empty cache so no test touches a real bucket."""
    mock = MagicMock()
    mock.get_object_bytes = AsyncMock(side_effect=_no_such_key())
    mock.put_object_bytes = AsyncMock()
    with patch("app.services.tts_preview_service.MinIOStorage", return_value=mock):
        yield mock


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


def test_validate_request_overrides_config_default_language_with_requested_language():
    # tts_config omits language; SarvamTTSConfig's own pydantic default ("hi")
    # must not win over the request's actual, already-voice-checked language.
    validated = validate_request(
        {"provider": "sarvam", "model": "bulbul:v3", "voice": "shubh"}, "ta", "hello"
    )
    assert validated["language"] == "ta"


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


def test_voice_is_supported_false_for_unrecognized_language_code():
    # "language" must be the canonical id ("en"), not a vendor-style code
    # like "en-US" — resolve_settings would otherwise return {} the same
    # way it does for a valid-but-voiceless language, silently passing.
    assert not _voice_is_supported(
        {"provider": "openai", "model": "gpt-4o-mini-tts", "voice": "alloy"}, "en-US"
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
        "app.services.tts_preview_service.check_rate_limit", new_callable=AsyncMock
    ), patch(
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
        "app.services.tts_preview_service.check_rate_limit", new_callable=AsyncMock
    ), patch(
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
        patch("app.services.tts_preview_service.check_rate_limit", new_callable=AsyncMock),
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
        "app.services.tts_preview_service.check_rate_limit", new_callable=AsyncMock
    ), patch(
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


def test_check_rate_limit_allows_first_request_and_sets_expiry():
    mock_redis = AsyncMock()
    mock_redis.incr.return_value = 1
    with patch(
        "app.services.tts_preview_service._get_redis", AsyncMock(return_value=mock_redis)
    ):
        _run(check_rate_limit("org-1"))
    mock_redis.expire.assert_awaited_once()


def test_check_rate_limit_raises_rate_limited_once_over_limit():
    mock_redis = AsyncMock()
    mock_redis.incr.return_value = 21  # default TTS_PREVIEW_RATE_LIMIT_PER_MINUTE is 20
    with patch(
        "app.services.tts_preview_service._get_redis", AsyncMock(return_value=mock_redis)
    ):
        with pytest.raises(TtsPreviewError) as exc_info:
            _run(check_rate_limit("org-1"))
    assert exc_info.value.reason == TtsPreviewErrorReason.RATE_LIMITED
    assert exc_info.value.retry_after is not None
    assert 0 < exc_info.value.retry_after <= 60


def test_check_rate_limit_does_not_reset_expiry_after_first_request():
    mock_redis = AsyncMock()
    mock_redis.incr.return_value = 5
    with patch(
        "app.services.tts_preview_service._get_redis", AsyncMock(return_value=mock_redis)
    ):
        _run(check_rate_limit("org-1"))
    mock_redis.expire.assert_not_awaited()


_SARVAM = {"provider": "sarvam", "model": "bulbul:v3", "voice": "shubh"}


def test_generate_preview_cache_hit_skips_rate_limit_and_adapter(storage):
    storage.get_object_bytes.side_effect = None
    storage.get_object_bytes.return_value = b"cached"
    with patch(
        "app.services.tts_preview_service.check_rate_limit", new_callable=AsyncMock
    ) as mock_limit, patch(
        "app.services.tts_preview_service.synthesize_preview", new_callable=AsyncMock
    ) as mock_synthesize:
        audio = _run(generate_preview("org-1", _SARVAM, "hi", "hello"))
    assert audio == b"cached"
    mock_limit.assert_not_awaited()
    mock_synthesize.assert_not_awaited()
    storage.put_object_bytes.assert_not_awaited()


def test_generate_preview_cache_miss_stores_audio(storage):
    patches = _patch_configured_sarvam()
    with patches[0], patches[1], patch(
        "app.services.tts_preview_service.check_rate_limit", new_callable=AsyncMock
    ), patch(
        "app.services.tts_preview_service.synthesize_preview",
        new_callable=AsyncMock,
        return_value=b"fresh",
    ):
        audio = _run(generate_preview("org-1", _SARVAM, "hi", "hello"))
    assert audio == b"fresh"
    key, data = storage.put_object_bytes.call_args.args
    assert key.startswith("org-1/") and data == b"fresh"
    assert storage.put_object_bytes.call_args.kwargs["content_type"] == "audio/wav"


def test_generate_preview_minio_errors_fall_through_to_synthesis(storage):
    storage.get_object_bytes.side_effect = ConnectionError("minio down")
    storage.put_object_bytes.side_effect = ConnectionError("minio down")
    patches = _patch_configured_sarvam()
    with patches[0], patches[1], patch(
        "app.services.tts_preview_service.check_rate_limit", new_callable=AsyncMock
    ), patch(
        "app.services.tts_preview_service.synthesize_preview",
        new_callable=AsyncMock,
        return_value=b"fresh",
    ):
        audio = _run(generate_preview("org-1", _SARVAM, "hi", "hello"))
    assert audio == b"fresh"


def test_build_cache_key_is_scoped_by_org_and_stable():
    key = build_cache_key("org-1", {"voice": "a", "model": "m"}, "hello")
    assert key.startswith("org-1/") and key.endswith(".wav")
    assert key == build_cache_key("org-1", {"model": "m", "voice": "a"}, "hello")
    assert key != build_cache_key("org-2", {"voice": "a", "model": "m"}, "hello")
    assert key != build_cache_key("org-1", {"voice": "b", "model": "m"}, "hello")
    assert key != build_cache_key("org-1", {"voice": "a", "model": "m"}, "hi")
