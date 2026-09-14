"""Helpers for wiring Pipecat STTUpdateSettingsFrame → provider set_language."""

from __future__ import annotations

from typing import Any

from pipecat.services.settings import STTSettings, is_given


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
        wire = (
            service._settings.language
            if getattr(service, "_settings", None) is not None
            and service._settings.language is not None
            else delta.language
        )
        await service.set_language(str(wire))
    return changed
