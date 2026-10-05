"""Unit tests for validation, placeholder stripping, config resolution, rate limit and cache."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import redis.asyncio as aioredis
from minio.error import S3Error

from apps.providers.preview import PreviewProviderError

from app.config import settings
from app.services.tts_preview_service import (
    _CACHE_CONNECT_TIMEOUT_S,
    _CACHE_TIMEOUT_S,
    _RATE_LIMIT_WINDOW_S,
    PREVIEW_MEDIA_TYPE,
    TtsPreviewError,
    TtsPreviewErrorReason,
    _get_redis,
    _get_storage,
    _voice_is_supported,
    build_cache_key,
    check_rate_limit,
    generate_preview,
    resolve_config,
    strip_placeholders,
    validate_request,
)

_SVC = "app.services.tts_preview_service"
_SARVAM = {"provider": "sarvam", "model": "bulbul:v3", "voice": "shubh"}


def _run(coro):
    return asyncio.run(coro)


async def _hang(*_args, **_kwargs):
    await asyncio.Event().wait()  # never set: only a timeout can end it


def _no_such_key() -> S3Error:
    return S3Error(MagicMock(), "NoSuchKey", "missing", "key", "req", "host")


def _patch_configured_sarvam() -> tuple:
    return (
        patch(f"{_SVC}.auth_service.list_configured_providers", return_value=["sarvam"]),
        patch(
            f"{_SVC}.auth_service.get_provider_auth",
            return_value={"auth": {"api_key": "secret-key"}},
        ),
    )


@contextmanager
def _patch_synthesis(**adapter: object) -> Iterator[tuple[AsyncMock, AsyncMock]]:
    """Configured Sarvam org, a no-op rate limit and a mocked adapter call.

    ``adapter`` is passed to the ``synthesize_preview`` mock (``return_value``
    or ``side_effect``). Yields ``(rate_limit_mock, adapter_mock)``.
    """
    with ExitStack() as stack:
        for p in _patch_configured_sarvam():
            stack.enter_context(p)
        limit = stack.enter_context(patch(f"{_SVC}.check_rate_limit", new_callable=AsyncMock))
        synth = stack.enter_context(
            patch(f"{_SVC}.synthesize_preview", new_callable=AsyncMock, **adapter)
        )
        yield limit, synth


def _preview(text: str = "hello") -> bytes:
    return _run(generate_preview("org-1", _SARVAM, "hi", text))


def _check_rate_limit_with(**incr: object) -> AsyncMock:
    """Run check_rate_limit with Redis INCR configured by ``incr``; return the Redis mock."""
    mock_redis = AsyncMock()
    mock_redis.incr.configure_mock(**incr)
    with patch(f"{_SVC}._get_redis", AsyncMock(return_value=mock_redis)):
        _run(check_rate_limit("org-1"))
    return mock_redis


@pytest.fixture(autouse=True)
def storage():
    """Stub MinIO with an empty cache so no test touches a real bucket."""
    mock = MagicMock()
    mock.get_object_bytes = AsyncMock(side_effect=_no_such_key())
    mock.put_object_bytes = AsyncMock()
    with patch(f"{_SVC}._get_storage", return_value=mock):
        yield mock


# --- placeholders and validation ---


def test_strip_placeholders_removes_braces_and_collapses_space_before_punctuation():
    assert strip_placeholders("Namaste {{name}}, welcome!") == "Namaste, welcome!"


def test_strip_placeholders_collapses_double_spaces():
    assert strip_placeholders("Hello  {{name}}  there") == "Hello there"


def test_empty_text_after_stripping_returns_empty_text_reason():
    # Act
    with pytest.raises(TtsPreviewError) as exc_info:
        validate_request(_SARVAM, "hi", "")

    # Assert
    assert exc_info.value.reason == TtsPreviewErrorReason.EMPTY_TEXT


def test_oversized_text_returns_oversized_reason():
    # Arrange
    with patch.object(settings, "TTS_PREVIEW_MAX_CHARS", 5):
        # Act
        with pytest.raises(TtsPreviewError) as exc_info:
            validate_request(_SARVAM, "hi", "too long text")

    # Assert
    assert exc_info.value.reason == TtsPreviewErrorReason.OVERSIZED


def test_invalid_config_returns_invalid_config_reason():
    # Act
    with pytest.raises(TtsPreviewError) as exc_info:
        validate_request({"provider": "not-a-real-provider"}, "hi", "hello")

    # Assert
    assert exc_info.value.reason == TtsPreviewErrorReason.INVALID_CONFIG


def test_provider_without_preview_adapter_returns_unsupported_voice_reason():
    # Arrange
    elevenlabs = {"provider": "elevenlabs", "model": "eleven_v3", "voice": "some-voice"}

    # Act
    with pytest.raises(TtsPreviewError) as exc_info:
        validate_request(elevenlabs, "en", "hello")

    # Assert
    assert exc_info.value.reason == TtsPreviewErrorReason.UNSUPPORTED_VOICE


def test_valid_sarvam_config_passes_validation():
    assert validate_request(_SARVAM, "hi", "hello")["provider"] == "sarvam"


def test_validate_request_overrides_config_default_language_with_requested_language():
    # tts_config omits language; SarvamTTSConfig's own pydantic default ("hi")
    # must not win over the request's actual, already-voice-checked language.
    assert validate_request(_SARVAM, "ta", "hello")["language"] == "ta"


def test_voice_is_supported_true_for_sarvam_custom_voice():
    assert _voice_is_supported({**_SARVAM, "voice": "totally-custom-voice"}, "hi")


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


# --- config resolution ---


def test_resolve_config_raises_not_configured_when_provider_missing():
    # Arrange
    with patch(f"{_SVC}.auth_service.list_configured_providers", return_value=[]):
        # Act
        with pytest.raises(TtsPreviewError) as exc_info:
            _run(resolve_config("org-1", _SARVAM))

    # Assert
    assert exc_info.value.reason == TtsPreviewErrorReason.NOT_CONFIGURED


def test_resolve_config_builds_typed_config_from_blob_and_auth():
    # Arrange
    configured, auth = _patch_configured_sarvam()

    # Act
    with configured, auth:
        cfg = _run(resolve_config("org-1", _SARVAM))

    # Assert
    assert cfg.api_key == "secret-key"
    assert cfg.voice == "shubh"


# --- generate_preview ---


def test_generate_preview_returns_audio_on_success():
    # Act
    with _patch_synthesis(return_value=b"RIFF....WAVEfmt "):
        audio = _preview("Namaste {{name}}")

    # Assert
    assert audio == b"RIFF....WAVEfmt "


def test_generate_preview_strips_placeholders_before_synthesis():
    # Act
    with _patch_synthesis(return_value=b"audio") as (_limit, mock_synthesize):
        _preview("Namaste {{name}}, welcome!")

    # Assert
    assert mock_synthesize.call_args.args[2] == "Namaste, welcome!"


def test_generate_preview_maps_timeout_to_timeout_reason():
    # Arrange
    with _patch_synthesis(side_effect=_hang), patch.object(settings, "TTS_PREVIEW_TIMEOUT_S", 0.01):
        # Act
        with pytest.raises(TtsPreviewError) as exc_info:
            _preview()

    # Assert
    assert exc_info.value.reason == TtsPreviewErrorReason.TIMEOUT


def test_generate_preview_maps_provider_error_to_upstream_reason():
    # Arrange
    with _patch_synthesis(side_effect=PreviewProviderError("vendor exploded")):
        # Act
        with pytest.raises(TtsPreviewError) as exc_info:
            _preview()

    # Assert
    assert exc_info.value.reason == TtsPreviewErrorReason.UPSTREAM
    assert "vendor exploded" not in str(exc_info.value)  # detail stays in the log


# --- rate limit ---


def test_check_rate_limit_allows_first_request_and_sets_expiry():
    # Act
    mock_redis = _check_rate_limit_with(return_value=1)

    # Assert
    mock_redis.expire.assert_awaited_once()


def test_check_rate_limit_raises_rate_limited_once_over_limit():
    # Act
    with pytest.raises(TtsPreviewError) as exc_info:
        _check_rate_limit_with(return_value=settings.TTS_PREVIEW_RATE_LIMIT_PER_MINUTE + 1)

    # Assert
    assert exc_info.value.reason == TtsPreviewErrorReason.RATE_LIMITED
    assert exc_info.value.retry_after is not None
    assert 0 < exc_info.value.retry_after <= _RATE_LIMIT_WINDOW_S


def test_check_rate_limit_does_not_reset_expiry_after_first_request():
    # Act
    mock_redis = _check_rate_limit_with(return_value=5)

    # Assert
    mock_redis.expire.assert_not_awaited()


def test_check_rate_limit_fails_open_when_redis_is_down():
    # Act / Assert: must not raise
    _check_rate_limit_with(side_effect=aioredis.ConnectionError("redis down"))


def test_redis_client_has_socket_timeouts():
    # Arrange
    with patch(f"{_SVC}._redis_client", None), patch(
        f"{_SVC}.aioredis.from_url", AsyncMock()
    ) as mock_from_url:
        # Act
        _run(_get_redis())

    # Assert
    kwargs = mock_from_url.call_args.kwargs
    assert kwargs["socket_timeout"] and kwargs["socket_connect_timeout"]


# --- cache ---


def test_generate_preview_cache_hit_skips_rate_limit_and_adapter(storage):
    # Arrange
    storage.get_object_bytes.side_effect = None
    storage.get_object_bytes.return_value = b"cached"

    # Act
    with _patch_synthesis() as (mock_limit, mock_synthesize):
        audio = _preview()

    # Assert
    assert audio == b"cached"
    mock_limit.assert_not_awaited()
    mock_synthesize.assert_not_awaited()
    storage.put_object_bytes.assert_not_awaited()


def test_generate_preview_cache_miss_stores_audio(storage):
    # Act
    with _patch_synthesis(return_value=b"fresh"):
        audio = _preview()

    # Assert
    assert audio == b"fresh"
    key, data = storage.put_object_bytes.call_args.args
    assert key.startswith("org-1/") and data == b"fresh"
    assert storage.put_object_bytes.call_args.kwargs["content_type"] == PREVIEW_MEDIA_TYPE


def test_generate_preview_minio_errors_fall_through_to_synthesis(storage):
    # Arrange
    storage.get_object_bytes.side_effect = ConnectionError("minio down")
    storage.put_object_bytes.side_effect = ConnectionError("minio down")

    # Act
    with _patch_synthesis(return_value=b"fresh"):
        audio = _preview()

    # Assert
    assert audio == b"fresh"


def test_generate_preview_slow_cache_get_falls_through_to_synthesis(storage):
    # Arrange
    storage.get_object_bytes.side_effect = _hang

    # Act
    with _patch_synthesis(return_value=b"fresh"), patch(f"{_SVC}._CACHE_TIMEOUT_S", 0.01):
        audio = _preview()

    # Assert
    assert audio == b"fresh"


def test_generate_preview_does_not_cache_empty_audio(storage):
    # Act
    with _patch_synthesis(return_value=b""):
        _preview()

    # Assert
    storage.put_object_bytes.assert_not_awaited()


def test_build_cache_key_is_scoped_by_org_and_stable():
    # Act
    key = build_cache_key("org-1", {"voice": "a", "model": "m"}, "hello")

    # Assert
    assert key.startswith("org-1/") and key.endswith(".wav")
    assert key == build_cache_key("org-1", {"model": "m", "voice": "a"}, "hello")
    assert key != build_cache_key("org-2", {"voice": "a", "model": "m"}, "hello")
    assert key != build_cache_key("org-1", {"voice": "b", "model": "m"}, "hello")
    assert key != build_cache_key("org-1", {"voice": "a", "model": "m"}, "hi")


def test_storage_client_has_short_timeouts_and_no_retries():
    # Arrange: _get_storage was imported before the autouse fixture patched it.
    with patch(f"{_SVC}._storage", None), patch(f"{_SVC}.MinIOStorage"), patch(
        f"{_SVC}.urllib3.PoolManager"
    ) as mock_pool:
        # Act
        _get_storage()

    # Assert
    kwargs = mock_pool.call_args.kwargs
    assert kwargs["timeout"].connect_timeout == _CACHE_CONNECT_TIMEOUT_S
    assert kwargs["timeout"].read_timeout == _CACHE_TIMEOUT_S
    assert kwargs["retries"].total == 0
