"""Generate a live TTS preview for an unsaved agent config.

Never runs through ``apps/runtime`` or Pipecat: calls the vendor's REST API
directly via ``apps/providers/preview.py`` adapters, so a burst of previews
can never compete with a live call for the runtime's event loop or GPU.
"""

from __future__ import annotations

import asyncio
import logging
import re
from enum import Enum
from typing import Any

import httpx
from pydantic import ValidationError

from apps.providers.base import Kind
from apps.providers.capabilities import api_capabilities
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

logger = logging.getLogger(__name__)

_PLACEHOLDER_RE = re.compile(r"\{\{\s*\w+\s*\}\}")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.!?;:])")
_WHITESPACE_RE = re.compile(r"\s+")

import_vendor_previews()


class TtsPreviewErrorReason(str, Enum):
    """Machine-readable reason a preview could not be generated."""

    EMPTY_TEXT = "empty_text"
    OVERSIZED = "oversized"
    INVALID_CONFIG = "invalid_config"
    UNSUPPORTED_VOICE = "unsupported_voice"
    NOT_CONFIGURED = "not_configured"
    TIMEOUT = "timeout"
    UPSTREAM = "upstream"


class TtsPreviewError(Exception):
    """Carries a :class:`TtsPreviewErrorReason` for the router to map to a status."""

    def __init__(self, reason: TtsPreviewErrorReason, message: str) -> None:
        self.reason = reason
        super().__init__(message)


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
    supporting any voice.
    """
    provider = str(blob.get("provider") or "")
    model = str(blob.get("model") or "")
    voice = blob.get("voice")
    cls = _config_class(Kind.TTS, provider)
    tree = getattr(cls, "settings_by_model_language", None)
    if not tree:
        return True
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
    """Validate, resolve config and synthesize one preview clip.

    Ends with exactly one log line; never logs preview text or credentials.
    """
    stripped = strip_placeholders(text)
    validated_blob = validate_request(tts_config, language, stripped)
    cfg = await resolve_config(org_id, validated_blob)
    provider = str(validated_blob.get("provider") or "")

    try:
        # httpx's own default timeout is 5s; without overriding it here it can
        # fire before our intended TTS_PREVIEW_TIMEOUT_S window elapses.
        async with httpx.AsyncClient(timeout=settings.TTS_PREVIEW_TIMEOUT_S) as client:
            async with asyncio.timeout(settings.TTS_PREVIEW_TIMEOUT_S):
                audio = await synthesize_preview(provider, cfg, stripped, client)
    except TimeoutError as exc:
        logger.info(
            "tts_preview timeout org=%s provider=%s model=%s chars=%d",
            org_id, provider, validated_blob.get("model"), len(stripped),
        )
        raise TtsPreviewError(TtsPreviewErrorReason.TIMEOUT, "Voice preview timed out") from exc
    except PreviewProviderError as exc:
        logger.info(
            "tts_preview upstream_error org=%s provider=%s model=%s chars=%d",
            org_id, provider, validated_blob.get("model"), len(stripped),
        )
        raise TtsPreviewError(TtsPreviewErrorReason.UPSTREAM, str(exc)) from exc

    logger.info(
        "tts_preview ok org=%s provider=%s model=%s chars=%d bytes=%d",
        org_id, provider, validated_blob.get("model"), len(stripped), len(audio),
    )
    return audio


# Exposed for capability lookups used by adapters and future settings checks.
__all__ = [
    "TtsPreviewError",
    "TtsPreviewErrorReason",
    "generate_preview",
    "resolve_config",
    "strip_placeholders",
    "validate_request",
    "api_capabilities",
]
