"""Shared Pipecat TTS client for model-server's OpenAI-compatible speech slot.

Every self-hosted TTS model in ``model-server/tts/`` answers the same contract:
``POST /v1/audio/speech`` with OpenAI's request body, streaming raw mono PCM
back and naming its rate in ``X-Sample-Rate``. The four local TTS providers
(``indic_orpheus``, ``rumik_oss``, ``indic_parler``, ``indic_mio``) used to carry
near-identical copies of this client; each now subclasses this one and sets
only what its model actually changes:

* ``LABEL`` -- the name in log lines and error frames.
* ``NATIVE_SAMPLE_RATE`` -- the rate the model emits (24 kHz or 44.1 kHz).
* ``SENDS_STYLE`` -- whether ``style`` goes out as OpenAI ``instructions``.
  Indic-Mio accepts the field and ignores it, so it does not send it.
* ``VOICE_OPTIONAL`` -- whether a request may carry no named speaker. Parler
  prompts with the style description alone when ``voice`` is empty.

Why not Pipecat's own ``OpenAITTSService``: it hard-rejects any voice name that
is not one of OpenAI's, and every model here has its own roster.

This module is not a provider. ``registry.load_providers()`` imports only
packages under ``local/``, so a plain module here is never mistaken for one.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import ClassVar

from loguru import logger
from openai import AsyncOpenAI, BadRequestError
from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.utils.tracing.service_decorators import traced_tts


class ModelServerSpeechTTSService(TTSService):
    """Stream PCM from a model-server TTS slot's ``POST /v1/audio/speech``."""

    LABEL: ClassVar[str] = "Model-server TTS"
    NATIVE_SAMPLE_RATE: ClassVar[int] = 24000
    SENDS_STYLE: ClassVar[bool] = True
    VOICE_OPTIONAL: ClassVar[bool] = False

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        voice: str | None,
        style: str | None = None,
        sample_rate: int | None = None,
        **kwargs,
    ):
        rate = sample_rate if sample_rate is not None else self.NATIVE_SAMPLE_RATE
        if rate != self.NATIVE_SAMPLE_RATE:
            logger.warning(
                "{} TTS only supports {}Hz sample rate. "
                "Current rate of {}Hz may cause issues.",
                self.LABEL,
                self.NATIVE_SAMPLE_RATE,
                rate,
            )

        voice = voice.strip() if voice else None
        # The servers read the language from the text's script, so there is no
        # language to send; None (not NOT_GIVEN) tells Pipecat that on purpose.
        settings = TTSSettings(model=model, voice=voice, language=None)

        super().__init__(
            sample_rate=rate,
            push_start_frame=True,
            push_stop_frames=True,
            settings=settings,
            **kwargs,
        )

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._voice = voice
        self._style = style.strip() if (self.SENDS_STYLE and style) else None

        if self.SENDS_STYLE:
            logger.info(
                "{} TTS initialized | base_url={} model={} voice={} style={}",
                self.LABEL,
                base_url,
                model,
                self._voice,
                self._style,
            )
        else:
            logger.info(
                "{} TTS initialized | base_url={} model={} voice={}",
                self.LABEL,
                base_url,
                model,
                self._voice,
            )

    def can_generate_metrics(self) -> bool:
        return True

    async def start(self, frame):
        await super().start(frame)
        if self.sample_rate != self.NATIVE_SAMPLE_RATE:
            logger.warning(
                "{} TTS requires {}Hz sample rate. "
                "Current rate of {}Hz may cause issues.",
                self.LABEL,
                self.NATIVE_SAMPLE_RATE,
                self.sample_rate,
            )

    def _missing_voice_error(self) -> str | None:
        """Why this request cannot be sent, or None if it can."""
        if self._voice:
            return None
        if self.VOICE_OPTIONAL:
            if self._style:
                return None
            return f"{self.LABEL} TTS needs a voice or a style description"
        return f"{self.LABEL} TTS voice must be specified"

    def _request_params(self, text: str) -> dict:
        # voice is always sent: the OpenAI SDK makes it a required keyword. An
        # empty string is the wire form of "no named speaker" for a model that
        # allows one (see VOICE_OPTIONAL); for the rest _missing_voice_error has
        # already refused the request.
        #
        # response_format is pinned to pcm (signed 16-bit): some slots default to
        # mp3 (OpenAI's default) or float32, which Pipecat cannot push as is.
        params: dict = {
            "input": text,
            "model": self._model,
            "voice": self._voice or "",
            "response_format": "pcm",
        }
        if self._style:
            params["instructions"] = self._style
        return params

    @traced_tts
    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        if not text.strip():
            return

        refusal = self._missing_voice_error()
        if refusal:
            yield ErrorFrame(error=refusal)
            return

        try:
            async with self._client.audio.speech.with_streaming_response.create(
                **self._request_params(text)
            ) as response:
                if response.status_code != 200:
                    error = await response.text()
                    logger.error(
                        "{} error getting audio (status: {}, error: {})",
                        self,
                        response.status_code,
                        error,
                    )
                    yield ErrorFrame(
                        error=(
                            f"Error getting audio (status: {response.status_code}, "
                            f"error: {error})"
                        )
                    )
                    return

                # The rate is pinned at construction because Pipecat needs it
                # before the first byte; a server reporting another rate is
                # logged rather than played at the wrong speed in silence.
                served_rate = response.headers.get("x-sample-rate")
                if served_rate and served_rate != str(self.sample_rate):
                    logger.error(
                        "{} served {}Hz audio but the pipeline expects {}Hz; "
                        "it will play at the wrong speed",
                        self.LABEL,
                        served_rate,
                        self.sample_rate,
                    )

                await self.start_tts_usage_metrics(text)

                async for chunk in response.iter_bytes(self.chunk_size):
                    if len(chunk) > 0:
                        await self.stop_ttfb_metrics()
                        yield TTSAudioRawFrame(
                            chunk,
                            self.sample_rate,
                            1,
                            context_id=context_id,
                        )
        except BadRequestError as exc:
            logger.error("{} TTS bad request | context_id={} error={}", self.LABEL, context_id, exc)
            yield ErrorFrame(error=f"Unknown error occurred: {exc}")
        except Exception as exc:
            logger.error("{} TTS error | context_id={} error={}", self.LABEL, context_id, exc)
            yield ErrorFrame(error=f"TTS error: {exc}")
