"""Indic Parler TTS — model-server OpenAI speech client.

All of the client lives in ``local/_openai_speech.py``; this subclass only sets
what Parler changes:

* **44.1 kHz.** Parler's DAC vocoder rate. The engine's native wire is float32;
  the shared client asks for ``pcm`` (16-bit), which the server converts to.
* **``voice`` is optional.** The server prompts the model with
  ``"{voice}. {instructions}"``, or the instructions alone when ``voice`` is
  empty -- which is how languages with no named speaker on the model card are
  served. An empty voice with no style is still refused.

Barge-in needs nothing extra: Pipecat cancels the task reading the response,
the connection closes, and the server evicts the request from its batch.
"""

from __future__ import annotations

from .._openai_speech import ModelServerSpeechTTSService
from .catalog import DEFAULT_TTS_STYLE, DEFAULT_TTS_VOICE, SAMPLE_RATE, TTS_MODEL


class IndicParlerTTSService(ModelServerSpeechTTSService):
    """Stream PCM from model-server Indic Parler ``POST /v1/audio/speech``."""

    LABEL = "Indic Parler"
    NATIVE_SAMPLE_RATE = SAMPLE_RATE
    SENDS_STYLE = True
    VOICE_OPTIONAL = True

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str = TTS_MODEL,
        voice: str | None = DEFAULT_TTS_VOICE,
        style: str | None = DEFAULT_TTS_STYLE,
        sample_rate: int | None = None,
        **kwargs,
    ):
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model=model,
            voice=voice,
            style=style,
            sample_rate=sample_rate,
            **kwargs,
        )
