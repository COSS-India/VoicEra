"""Higgs TTS 3 — model-server OpenAI speech client.

All of the client lives in ``local/_openai_speech.py``; this subclass only sets
what Higgs changes. It emits 24 kHz signed 16-bit PCM, like Orpheus and Rumik.

``style`` goes out as OpenAI ``instructions``, which the server turns into the
model's leading control tags. Unlike Rumik, where any text conditions the
delivery, the server takes only its fixed tag list and answers anything else
with a 400 -- so a bad style fails the first sentence loudly rather than being
read aloud. ``none`` is plain delivery and is sent as no instructions at all.

On a barge-in Pipecat cancels the task reading the response, the connection
closes, and the server closes its own request to the SGLang-Omni sidecar, which
aborts generation there.
"""

from __future__ import annotations

from .._openai_speech import ModelServerSpeechTTSService
from .catalog import (
    DEFAULT_TTS_STYLE,
    DEFAULT_TTS_VOICE,
    NO_STYLE,
    SAMPLE_RATE,
    TTS_MODEL,
)


class HiggsTTSService(ModelServerSpeechTTSService):
    """Stream PCM from model-server Higgs TTS 3 ``POST /v1/audio/speech``."""

    LABEL = "Higgs TTS"
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
        # "none" is the dropdown's word for no tags; send no instructions for it
        # rather than relying on the server to recognise the word.
        if style and style.strip().lower() == NO_STYLE:
            style = None
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model=model,
            voice=voice,
            style=style,
            sample_rate=sample_rate,
            **kwargs,
        )
