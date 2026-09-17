"""Helpers for wiring Pipecat UpdateSettings frames to first-party adapters.

Stock Pipecat services already apply language / voice / model via ``_settings``.
Custom adapters keep those knobs on private attributes (``_language``,
``_voice``, ``_model``) and need an extra copy after ``super()._update_settings``.
"""

from __future__ import annotations

from typing import Any

from pipecat.services.settings import STTSettings, TTSSettings, is_given


def _stored_or_delta(service: Any, attr: str, delta_value: Any) -> Any:
    settings = getattr(service, "_settings", None)
    stored = getattr(settings, attr, None) if settings is not None else None
    return stored if stored is not None else delta_value


async def update_stt_settings_with_language(
    service: Any,
    delta: STTSettings,
    *,
    super_update,
) -> dict[str, Any]:
    """Apply ``delta``, then call ``service.set_language`` when language changed.

    Custom STT adapters keep language on a private ``_language`` attribute and
    expose ``set_language``. Stock Pipecat services already handle language via
    ``_settings``; this helper bridges UpdateSettings frames to those adapters.
    """
    lang_requested = is_given(delta.language) and delta.language is not None
    changed = await super_update(delta)
    if lang_requested and hasattr(service, "set_language"):
        await service.set_language(str(_stored_or_delta(service, "language", delta.language)))
    return changed


async def update_tts_settings_with_voice_language(
    service: Any,
    delta: TTSSettings,
    *,
    super_update,
) -> dict[str, Any]:
    """Apply ``delta``, then copy voice / language / model onto private attrs.

    Do not call ``TTSService.set_voice`` here — the base method wraps
    ``_update_settings`` and would recurse. Custom TTS reads ``_voice``,
    ``_language``, and ``_model`` in ``run_tts``.
    """
    voice_requested = is_given(delta.voice) and delta.voice is not None
    lang_requested = is_given(delta.language) and delta.language is not None
    model_requested = is_given(delta.model) and delta.model is not None
    changed = await super_update(delta)
    if lang_requested and hasattr(service, "_language"):
        service._language = str(_stored_or_delta(service, "language", delta.language))
    if voice_requested and hasattr(service, "_voice"):
        service._voice = str(_stored_or_delta(service, "voice", delta.voice))
    if model_requested and hasattr(service, "_model"):
        service._model = str(_stored_or_delta(service, "model", delta.model))
    return changed
