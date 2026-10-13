"""Portuguese Chatterbox TTS for Pipecat.

model-server's ``tts/pt-chatterbox`` serves the slot's OpenAI speech route with
16-bit PCM at 24 kHz -- the same wire format as Orpheus -- so the streaming
client is the Orpheus one, with no style instructions. A subclass rather than a
re-use by name only so logs and metrics say which model a call was using.
"""

from __future__ import annotations

from ..indic_orpheus.tts import IndicOrpheusTTSService
from .catalog import DEFAULT_TTS_VOICE, TTS_MODEL


class PtChatterboxTTSService(IndicOrpheusTTSService):
    """Stream PCM from model-server ``POST /v1/audio/speech`` (pt-chatterbox)."""

    def __init__(self, *, api_key: str, base_url: str, model: str = TTS_MODEL,
                 voice: str = DEFAULT_TTS_VOICE, **kwargs):
        kwargs.pop("style", None)
        super().__init__(api_key=api_key, base_url=base_url, model=model,
                         voice=voice, style=None, **kwargs)
