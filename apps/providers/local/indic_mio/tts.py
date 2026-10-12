"""Indic-Mio TTS — OpenAI-compatible speech client for model-server.

Adapted from ``local/indic_parler/tts.py`` (itself from ``indic_orpheus``): the
same ``/v1/audio/speech`` contract on the same 44.1 kHz rate, and the same
reason for existing -- Pipecat's ``OpenAITTSService`` hard-rejects non-OpenAI
voice names. The difference is what is not sent: Indic-Mio accepts
``instructions`` and ignores it, so this client has no style to send.

The server streams from a vLLM sidecar. On a barge-in Pipecat cancels the task
reading this response, the connection closes, and the server lets the
cancellation propagate so the vLLM request is aborted rather than finished.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from loguru import logger
from openai import AsyncOpenAI, BadRequestError
from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.tts_service import TTSService
from pipecat.utils.tracing.service_decorators import traced_tts

from .catalog import DEFAULT_TTS_VOICE, SAMPLE_RATE, TTS_MODEL


class IndicMioTTSService(TTSService):
    """Stream PCM from model-server Indic-Mio ``POST /v1/audio/speech``."""

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
        rate = sample_rate if sample_rate is not None else SAMPLE_RATE
        if rate != SAMPLE_RATE:
            logger.warning(
                "Indic-Mio TTS only supports {}Hz sample rate. "
                "Current rate of {}Hz may cause issues.",
                SAMPLE_RATE,
                rate,
            )

        super().__init__(
            sample_rate=rate,
            push_start_frame=True,
            push_stop_frames=True,
            **kwargs,
        )

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._voice = voice.strip() if voice else None

        logger.info(
            "Indic-Mio TTS initialized | base_url={} model={} voice={}",
            base_url,
            model,
            self._voice,
        )

    def can_generate_metrics(self) -> bool:
        return True

    async def start(self, frame):
        await super().start(frame)
        if self.sample_rate != SAMPLE_RATE:
            logger.warning(
                "Indic-Mio TTS requires {}Hz sample rate. "
                "Current rate of {}Hz may cause issues.",
                SAMPLE_RATE,
                self.sample_rate,
            )

    @traced_tts
    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        if not text.strip():
            return

        if not self._voice:
            yield ErrorFrame(error="Indic-Mio TTS voice must be specified")
            return

        # response_format is pinned to pcm (16-bit): the server's default is
        # float32, which Pipecat would misread as 16-bit noise.
        create_params: dict = {
            "input": text,
            "model": self._model,
            "voice": self._voice,
            "response_format": "pcm",
        }

        try:
            async with self._client.audio.speech.with_streaming_response.create(
                **create_params
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

                served_rate = response.headers.get("x-sample-rate")
                if served_rate and served_rate != str(self.sample_rate):
                    logger.error(
                        "Indic-Mio served {}Hz audio but the pipeline expects {}Hz; "
                        "it will play at the wrong speed",
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
            logger.error("Indic-Mio TTS bad request | context_id={} error={}", context_id, exc)
            yield ErrorFrame(error=f"Unknown error occurred: {exc}")
        except Exception as exc:
            logger.error("Indic-Mio TTS error | context_id={} error={}", context_id, exc)
            yield ErrorFrame(error=f"TTS error: {exc}")
