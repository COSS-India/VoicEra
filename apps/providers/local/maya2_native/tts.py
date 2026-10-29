"""Maya 2 Native TTS — model-server OpenAI speech client.

The client lives in ``local/_openai_speech.py``; this subclass sets what Maya
changes. It emits 24 kHz signed 16-bit PCM, like Orpheus and Rumik, and has no
style.

The one real difference is ``language``. Every other local TTS server reads the
language from the text's script, so the shared client sends none. Maya takes a
language token, and the script cannot supply it: Marathi and Hindi share
Devanagari, Assamese and Bengali share a script. So this subclass keeps the
model's language code on ``_language`` and sends it as an OpenAI ``extra_body``
field. A mid-call language switch arrives as VoicEra's canonical id (``od``) and
is translated to the wire code (``or``) before Pipecat stores it; the shared
helper then copies it onto ``_language``.
"""

from __future__ import annotations

from typing import Any

from pipecat.services.settings import TTSSettings

from apps.providers.runtime_language import translate_delta_language

from .._openai_speech import ModelServerSpeechTTSService
from .catalog import DEFAULT_TTS_VOICE, SAMPLE_RATE, TTS_MODEL, resolve_wire_language


class Maya2NativeTTSService(ModelServerSpeechTTSService):
    """Stream PCM from model-server Maya 2 Native ``POST /v1/audio/speech``."""

    LABEL = "Maya 2 Native"
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
        language: str | None = "hi",
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
        self._language = resolve_wire_language(language) if language else None

    async def _update_settings(self, delta: TTSSettings) -> dict[str, Any]:
        translate_delta_language(delta, resolve_wire_language)
        return await super()._update_settings(delta)

    def _request_params(self, text: str) -> dict:
        params = super()._request_params(text)
        if self._language:
            params["extra_body"] = {"language": self._language}
        return params
