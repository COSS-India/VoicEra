"""Indic Conformer STT — Pipecat's OpenAI Realtime client pointed at model-server.

The model server's ``/v1/realtime`` speaks OpenAI Realtime transcription, so
Pipecat's own ``OpenAIRealtimeSTTService`` is the client. This subclass only
fixes the parts that differ from OpenAI:

* ``base_url`` is the gateway, which has no auth; the SDK-style bearer header
  still goes out, so the key is a placeholder string.
* ``turn_detection=False``: Silero in the pipeline ends the turn and the
  service commits the buffer on ``VADUserStoppedSpeakingFrame`` -- the same
  turn ownership ``indic_nemotron`` uses with ``flush_eos``.
* ``language`` is the raw wire code (``or``, ``bhb``, ``kok``...). Pipecat
  passes a string it does not recognise through unchanged.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from pipecat.services.openai.stt import OpenAIRealtimeSTTService
from pipecat.services.settings import STTSettings

from apps.providers.runtime_language import translate_delta_language

from .catalog import STT_MODEL, resolve_wire_language


class IndicConformerSTTService(OpenAIRealtimeSTTService):
    """Stream audio to model-server Conformer over ``/v1/realtime``."""

    def __init__(
        self,
        *,
        base_url: str,
        language: str = "hi",
        model: str = STT_MODEL,
        **kwargs,
    ):
        wire = language.strip().lower()
        super().__init__(
            api_key="not-needed",
            base_url=base_url,
            turn_detection=False,
            settings=OpenAIRealtimeSTTService.Settings(model=model, language=wire),
            **kwargs,
        )
        self._wire_language = wire
        self._catalog_model = model

        logger.info(
            "Indic Conformer STT initialized | base_url={} model={} language={}",
            base_url,
            model,
            wire,
        )

    async def _update_settings(self, delta: STTSettings) -> dict[str, Any]:
        """Apply a runtime settings change, such as a mid-call language switch.

        The switch carries VoicEra's canonical id (``od``, ``bh``); the server
        wants its wire code (``or``, ``bhb``). Translated here, Pipecat's own
        client then stores it and sends the ``session.update``.
        """
        translate_delta_language(
            delta, lambda lang: resolve_wire_language(self._catalog_model, lang)
        )
        changed = await super()._update_settings(delta)
        if "language" in changed:
            self._wire_language = str(self._settings.language)
            logger.info("Indic Conformer STT language switched to {}", self._wire_language)
        return changed
