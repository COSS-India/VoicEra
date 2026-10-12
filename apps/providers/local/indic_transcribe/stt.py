"""Indic Transcribe STT — Pipecat's OpenAI Realtime client pointed at model-server.

Same shape as ``local/indic_conformer/stt.py``, because both models answer the
same slot contract on ``/v1/realtime``. Pipecat's ``OpenAIRealtimeSTTService``
is the client; this subclass only fixes what differs from OpenAI:

* ``base_url`` is the gateway, which has no auth; the bearer header still goes
  out, so the key is a placeholder string.
* ``turn_detection=False``: Silero in the pipeline ends the turn and the service
  sends ``input_audio_buffer.commit`` on ``VADUserStoppedSpeakingFrame``. The
  server finalises that turn and opens the next one on the same socket.
* ``language`` is the raw wire code (``or``, ``bhb``, ``bho``...). The server
  opens in its own default language and switches on the ``session.update``
  Pipecat sends once the session is created -- before any audio, so the first
  turn is replaced rather than committed.
"""

from __future__ import annotations

from loguru import logger
from pipecat.services.openai.stt import OpenAIRealtimeSTTService

from .catalog import STT_MODEL


class IndicTranscribeSTTService(OpenAIRealtimeSTTService):
    """Stream audio to model-server Indic Transcribe over ``/v1/realtime``."""

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
            "Indic Transcribe STT initialized | base_url={} model={} language={}",
            base_url,
            model,
            wire,
        )
