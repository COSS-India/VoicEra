"""Portuguese Whisper STT for Pipecat.

model-server's ``stt/pt-whisper`` speaks the same ``/v1/asr/ws`` protocol as
``indic-nemotron`` -- ready on connect, PCM16 in, partials out, ``flush_eos``
on the pipeline's VAD stop -- so the client is the Nemotron one, unchanged.
A subclass rather than a re-use by name only so logs and metrics say which
model a call was using.
"""

from __future__ import annotations

from ..indic_nemotron.stt import IndicNemotronSTTService


class PtWhisperSTTService(IndicNemotronSTTService):
    """Stream PCM to model-server ``/v1/asr/ws`` (pt-whisper)."""

    def __init__(self, *, ws_url: str, language: str = "pt", **kwargs):
        super().__init__(ws_url=ws_url, language=language, **kwargs)
