"""Generate a live TTS preview for an unsaved agent config.

Never runs through ``apps/runtime`` or Pipecat: calls the vendor's REST API
directly via ``apps/providers/preview.py`` adapters, so a burst of previews
can never compete with a live call for the runtime's event loop or GPU.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from enum import Enum
from typing import Any

import httpx
import redis.asyncio as aioredis
from minio.error import S3Error
from pydantic import ValidationError

from apps.providers.base import Kind
from apps.providers.preview import (
    PreviewProviderError,
    has_preview_adapter,
    import_vendor_previews,
    synthesize_preview,
)
from apps.providers.schema import _config_class
from apps.providers.scoped_settings import resolve_settings

from app.config import settings
from app.services import auth_service
from app.services.agent_config_validation import (
    AgentConfigValidationError,
    validate_persisted_model_config,
)
from app.storage.minio_client import MinIOStorage

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\{\{\s*\w+\s*\}\}")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.!?;:])")
_WHITESPACE_RE = re.compile(r"\s+")
_RATE_LIMIT_WINDOW_S = 60
# Bump when an adapter's output changes for the same inputs (WAV header, sample
# rate, param mapping) so stale clips stop hitting; the bucket's 7-day
# lifecycle rule cleans up the orphans.
_CACHE_VERSION = 1
# Well under TTS_PREVIEW_TIMEOUT_S: the MinIO client's own default is 300 s,
# and a cache that's slower than synthesis is worse than no cache.
_CACHE_TIMEOUT_S = 2.0

import_vendor_previews()


class TtsPreviewErrorReason(str, Enum):
    """Machine-readable reason a preview could not be generated."""

    EMPTY_TEXT = "empty_text"
    OVERSIZED = "oversized"
    INVALID_CONFIG = "invalid_config"
    UNSUPPORTED_VOICE = "unsupported_voice"
    NOT_CONFIGURED = "not_configured"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    UPSTREAM = "upstream"


class TtsPreviewError(Exception):
    """Carries a :class:`TtsPreviewErrorReason` for the router to map to a status."""

    def __init__(
        self, reason: TtsPreviewErrorReason, message: str, *, retry_after: int | None = None
    ) -> None:
        self.reason = reason
        self.retry_after = retry_after
        super().__init__(message)


_redis_client: aioredis.Redis | None = None
_storage: MinIOStorage | None = None


def _get_storage() -> MinIOStorage:
    """Lazily create one shared MinIO client so connections are reused."""
    global _storage
    if _storage is None:
        _storage = MinIOStorage()
    return _storage


async def _get_redis() -> aioredis.Redis:
    """Lazily create a dedicated Redis client for preview rate limiting.

    A separate client from ``call_concurrency.rate_limiter``: that module's
    ``RateLimiter`` is a per-second sliding window shared with campaigns,
    not the per-minute fixed window previews need.
    """
    global _redis_client
    if _redis_client is None:
        _redis_client = await aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis_client


async def check_rate_limit(org_id: str) -> None:
    """Enforce ``TTS_PREVIEW_RATE_LIMIT_PER_MINUTE`` previews per org per minute.

    Fixed window keyed by the current epoch minute, so it resets on a clean
    minute boundary rather than sliding. Raises :class:`TtsPreviewError` with
    ``retry_after`` (seconds until the window resets) when over the limit.
    """
    now = time.time()
    window = int(now // _RATE_LIMIT_WINDOW_S)
    key = f"tts_preview_rl:{org_id}:{window}"
    try:
        redis_client = await _get_redis()
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, _RATE_LIMIT_WINDOW_S)
    except aioredis.RedisError:
        # Fail open: the limiter protects vendor spend, it must not take the
        # feature down with Redis (same default as Envoy ratelimit).
        logger.warning("tts_preview rate_limit_unavailable org=%s", org_id, exc_info=True)
        return
    if count > settings.TTS_PREVIEW_RATE_LIMIT_PER_MINUTE:
        retry_after = _RATE_LIMIT_WINDOW_S - int(now % _RATE_LIMIT_WINDOW_S)
        raise TtsPreviewError(
            TtsPreviewErrorReason.RATE_LIMITED,
            "Too many voice previews; please wait a moment",
            retry_after=retry_after,
        )


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def build_cache_key(org_id: str, blob: dict[str, Any], text: str) -> str:
    """Return the MinIO object key for a preview clip.

    ``blob`` must be the secret-free validated config. The org id prefixes
    the key so one org can never be served another org's cached clip.
    """
    payload = json.dumps(
        {"v": _CACHE_VERSION, "cfg": blob, "text": text},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return f"{org_id}/{hashlib.sha256(payload.encode()).hexdigest()}.wav"


async def get_cached(key: str) -> bytes | None:
    """Return cached audio, or ``None`` on a miss or any MinIO failure."""
    try:
        async with asyncio.timeout(_CACHE_TIMEOUT_S):
            return await _get_storage().get_object_bytes(
                key, bucket_name=settings.TTS_PREVIEW_BUCKET
            )
    except S3Error as exc:
        if exc.code != "NoSuchKey":
            logger.warning("tts_preview cache_get_failed code=%s", exc.code)
    except Exception:
        logger.warning("tts_preview cache_get_failed", exc_info=True)
    return None


async def put_cached(key: str, audio: bytes) -> None:
    """Store audio in the preview cache; best effort, never raises."""
    try:
        async with asyncio.timeout(_CACHE_TIMEOUT_S):
            await _get_storage().put_object_bytes(
                key, audio, bucket_name=settings.TTS_PREVIEW_BUCKET, content_type="audio/wav"
            )
    except Exception:
        logger.warning("tts_preview cache_put_failed", exc_info=True)


def strip_placeholders(text: str) -> str:
    """Remove ``{{name}}``-style placeholders and tidy the resulting spacing."""
    stripped = _PLACEHOLDER_RE.sub("", text)
    stripped = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", stripped)
    stripped = _WHITESPACE_RE.sub(" ", stripped)
    return stripped.strip()


def _voice_is_supported(blob: dict[str, Any], language: str) -> bool:
    """Check the requested voice against the model's settings tree.

    A provider that declares no settings tree, or no ``voice`` entry for
    ``(model, language)``, or allows custom voice input, is treated as
    supporting any voice. ``language`` must be one of the model's known
    canonical language ids: ``resolve_settings`` returns ``{}`` both when
    the language is unrecognized and when it's valid but has no voice
    metadata, so that case is distinguished here rather than silently
    treated as "voice supported".
    """
    provider = str(blob.get("provider") or "")
    model = str(blob.get("model") or "")
    voice = blob.get("voice")
    cls = _config_class(Kind.TTS, provider)
    tree = getattr(cls, "settings_by_model_language", None)
    if not tree:
        return True
    by_lang = tree.get(model)
    if by_lang and language not in by_lang:
        return False
    resolved = resolve_settings(tree, model, language)
    voice_meta = resolved.get("voice")
    if not voice_meta:
        return True
    if voice_meta.get("allow_custom_input"):
        return True
    options = voice_meta.get("options")
    if not options:
        return True
    return voice in options


def validate_request(tts_config: dict[str, Any], language: str, text: str) -> dict[str, Any]:
    """Validate text, config shape and voice/language support.

    Returns the secret-free, validated ``tts_config`` blob. Raises
    :class:`TtsPreviewError` on any failure.
    """
    if not text.strip():
        raise TtsPreviewError(TtsPreviewErrorReason.EMPTY_TEXT, "Preview text is empty")
    if len(text) > settings.TTS_PREVIEW_MAX_CHARS:
        raise TtsPreviewError(
            TtsPreviewErrorReason.OVERSIZED,
            f"Preview text exceeds {settings.TTS_PREVIEW_MAX_CHARS} characters",
        )

    try:
        validated = validate_persisted_model_config(Kind.TTS, tts_config)
    except AgentConfigValidationError as exc:
        raise TtsPreviewError(TtsPreviewErrorReason.INVALID_CONFIG, str(exc)) from exc

    provider = str(validated.get("provider") or "")
    if not has_preview_adapter(provider):
        raise TtsPreviewError(
            TtsPreviewErrorReason.UNSUPPORTED_VOICE,
            f"Preview is not available for provider {provider!r}",
        )
    if not _voice_is_supported(validated, language):
        raise TtsPreviewError(
            TtsPreviewErrorReason.UNSUPPORTED_VOICE,
            "Selected voice is not available for this language",
        )
    # validate_persisted_model_config fills a missing tts_config.language with
    # the provider's own pydantic default (e.g. Sarvam's "hi"), not the request's
    # language. _voice_is_supported already checked the voice against `language`
    # above, so it's the validated, authoritative value — make it win here too,
    # or synthesis silently uses the wrong language.
    validated["language"] = language
    return validated


async def resolve_config(org_id: str, blob: dict[str, Any]) -> Any:
    """Merge stored auth into the validated blob and build the typed config."""
    provider = str(blob.get("provider") or "")
    configured = await asyncio.to_thread(auth_service.list_configured_providers, org_id)
    if provider not in configured:
        raise TtsPreviewError(
            TtsPreviewErrorReason.NOT_CONFIGURED,
            f"Provider {provider!r} is not configured for this organisation",
        )

    stored = await asyncio.to_thread(auth_service.get_provider_auth, org_id, provider)
    auth = (stored or {}).get("auth") or {}
    cls = _config_class(Kind.TTS, provider)
    try:
        return cls.model_validate({**blob, **auth})
    except ValidationError as exc:
        # Never echo exc.errors() to the client: pydantic includes the offending
        # "input" for whole-model validators, which here can be {**blob, **auth}
        # (i.e. the real API key).
        logger.warning("tts_preview invalid_config org=%s provider=%s", org_id, provider)
        raise TtsPreviewError(
            TtsPreviewErrorReason.INVALID_CONFIG,
            f"Invalid configuration for provider {provider!r}",
        ) from exc


async def generate_preview(org_id: str, tts_config: dict[str, Any], language: str, text: str) -> bytes:
    """Validate, serve from cache or synthesize (and cache) one preview clip.

    Ends with exactly one log line; never logs preview text or credentials.
    """
    started = time.monotonic()
    stripped = strip_placeholders(text)
    validated_blob = validate_request(tts_config, language, stripped)
    provider = str(validated_blob.get("provider") or "")

    # Cache before the rate limit and the NOT_CONFIGURED check: a hit costs
    # the vendor nothing, and both exist to guard vendor calls. So an org that
    # removed its credentials can still replay clips it already heard, until
    # the bucket's 7-day expiry.
    cache_key = build_cache_key(org_id, validated_blob, stripped)
    cached = await get_cached(cache_key)
    if cached is not None:
        logger.info(
            "tts_preview ok org=%s provider=%s model=%s chars=%d bytes=%d cache=hit ms=%d",
            org_id, provider, validated_blob.get("model"), len(stripped), len(cached),
            _elapsed_ms(started),
        )
        return cached

    # Counted before the NOT_CONFIGURED check on purpose: like API gateways,
    # every request that reaches the limiter counts, 409s included.
    await check_rate_limit(org_id)
    cfg = await resolve_config(org_id, validated_blob)

    try:
        # httpx's own default timeout is 5s; without overriding it here it can
        # fire before our intended TTS_PREVIEW_TIMEOUT_S window elapses.
        async with httpx.AsyncClient(timeout=settings.TTS_PREVIEW_TIMEOUT_S) as client:
            async with asyncio.timeout(settings.TTS_PREVIEW_TIMEOUT_S):
                audio = await synthesize_preview(provider, cfg, stripped, client)
    except TimeoutError as exc:
        logger.info(
            "tts_preview timeout org=%s provider=%s model=%s chars=%d ms=%d",
            org_id, provider, validated_blob.get("model"), len(stripped), _elapsed_ms(started),
        )
        raise TtsPreviewError(TtsPreviewErrorReason.TIMEOUT, "Voice preview timed out") from exc
    except PreviewProviderError as exc:
        logger.info(
            "tts_preview upstream_error org=%s provider=%s model=%s chars=%d ms=%d error=%s",
            org_id, provider, validated_blob.get("model"), len(stripped), _elapsed_ms(started), exc,
        )
        # Generic to the client: the adapter's message can carry httpx
        # connection/DNS details. The detail is in the log line above.
        raise TtsPreviewError(
            TtsPreviewErrorReason.UPSTREAM, "Voice provider request failed"
        ) from exc

    if audio:
        await put_cached(cache_key, audio)
    logger.info(
        "tts_preview ok org=%s provider=%s model=%s chars=%d bytes=%d cache=miss ms=%d",
        org_id, provider, validated_blob.get("model"), len(stripped), len(audio),
        _elapsed_ms(started),
    )
    return audio


__all__ = [
    "TtsPreviewError",
    "TtsPreviewErrorReason",
    "build_cache_key",
    "check_rate_limit",
    "generate_preview",
    "resolve_config",
    "strip_placeholders",
    "validate_request",
]
