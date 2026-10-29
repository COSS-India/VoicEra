"""Indic-Mio TTS — model-server OpenAI speech client.

All of the client lives in ``local/_openai_speech.py``; this subclass only sets
what Indic-Mio changes: 44.1 kHz audio, like Parler, and no style. Indic-Mio
accepts ``instructions`` and ignores it, so ``SENDS_STYLE`` is off and the
constructor takes no style at all.

The server streams from a vLLM sidecar. On a barge-in Pipecat cancels the task
reading the response, the connection closes, and the server lets the
cancellation propagate so the vLLM request is aborted rather than finished.
"""

from __future__ import annotations

from .._openai_speech import ModelServerSpeechTTSService
from .catalog import DEFAULT_TTS_VOICE, SAMPLE_RATE, TTS_MODEL


class IndicMioTTSService(ModelServerSpeechTTSService):
    """Stream PCM from model-server Indic-Mio ``POST /v1/audio/speech``."""

    LABEL = "Indic-Mio"
    NATIVE_SAMPLE_RATE = SAMPLE_RATE
    SENDS_STYLE = False
    VOICE_OPTIONAL = False

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str = TTS_MODEL,
        voice: str = DEFAULT_TTS_VOICE,
        sample_rate: int | None = None,
        **kwargs,
    ):
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model=model,
            voice=voice,
            sample_rate=sample_rate,
            **kwargs,
        )
