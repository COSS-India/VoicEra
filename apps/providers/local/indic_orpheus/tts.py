"""Indic Orpheus TTS — model-server OpenAI speech client.

All of the client lives in ``local/_openai_speech.py``; this subclass only sets
what Orpheus changes. It emits 24 kHz signed 16-bit PCM, and ``style`` goes out
as OpenAI ``instructions``, which the server matches against the fixed Orpheus
v2 style roster (anything outside it is ignored rather than rejected).
"""

from __future__ import annotations

from .._openai_speech import ModelServerSpeechTTSService
from .catalog import DEFAULT_TTS_STYLE, DEFAULT_TTS_VOICE, SAMPLE_RATE, TTS_MODEL


class IndicOrpheusTTSService(ModelServerSpeechTTSService):
    """Stream PCM from model-server Orpheus ``POST /v1/audio/speech``."""

    LABEL = "Indic Orpheus"
    NATIVE_SAMPLE_RATE = SAMPLE_RATE
    SENDS_STYLE = True
    VOICE_OPTIONAL = False

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str = TTS_MODEL,
        voice: str = DEFAULT_TTS_VOICE,
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
