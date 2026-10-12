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

from loguru import logger
from pipecat.services.openai.stt import OpenAIRealtimeSTTService

from .catalog import STT_MODEL


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

        logger.info(
            "Indic Conformer STT initialized | base_url={} model={} language={}",
            base_url,
            model,
            wire,
        )
