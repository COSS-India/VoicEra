"""Rumik OSS-1 TTS — OpenAI-compatible speech client for model-server.

Adapted from ``local/indic_orpheus/tts.py``; the shape is the same because both
models answer the same slot contract on the same 24 kHz signed-16-bit wire.
Pipecat's own ``OpenAITTSService`` hard-rejects non-OpenAI voice names, so this
mirrors its streaming PCM client without the voice whitelist.

``style`` goes out as OpenAI ``instructions``, which the model server turns into
the model's ``<description="...">`` prefix. That is a different contract from
Orpheus, where ``instructions`` is matched against a fixed style roster and
ignored when it does not match: here any text conditions the delivery, so a
typo changes how the line is read rather than being silently dropped.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from loguru import logger
from openai import AsyncOpenAI, BadRequestError
from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.tts_service import TTSService
from pipecat.utils.tracing.service_decorators import traced_tts

from .catalog import DEFAULT_TTS_STYLE, DEFAULT_TTS_VOICE, SAMPLE_RATE, TTS_MODEL


class RumikOssTTSService(TTSService):
    """Stream PCM from model-server Rumik ``POST /v1/audio/speech``."""

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
        rate = sample_rate if sample_rate is not None else SAMPLE_RATE
        if rate != SAMPLE_RATE:
            logger.warning(
                "Rumik OSS TTS only supports {}Hz sample rate. "
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
        self._voice = voice
        self._style = style.strip() if style else None

        logger.info(
            "Rumik OSS TTS initialized | base_url={} model={} voice={} style={}",
            base_url,
            model,
            voice,
            self._style,
        )

    def can_generate_metrics(self) -> bool:
        return True

    async def start(self, frame):
        await super().start(frame)
        if self.sample_rate != SAMPLE_RATE:
            logger.warning(
                "Rumik OSS TTS requires {}Hz sample rate. "
                "Current rate of {}Hz may cause issues.",
                SAMPLE_RATE,
                self.sample_rate,
            )

    @traced_tts
    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        if not text.strip():
            return

        if not self._voice:
            yield ErrorFrame(error="Rumik OSS TTS voice must be specified")
            return

        # response_format is pinned to pcm rather than left to the server's
        # default: the slot's default is mp3, which is OpenAI's, and Pipecat
        # wants raw frames it can push without decoding.
        create_params: dict = {
            "input": text,
            "model": self._model,
            "voice": self._voice,
            "response_format": "pcm",
        }
        if self._style:
            create_params["instructions"] = self._style

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
            logger.error("Rumik OSS TTS bad request | context_id={} error={}", context_id, exc)
            yield ErrorFrame(error=f"Unknown error occurred: {exc}")
        except Exception as exc:
            logger.error("Rumik OSS TTS error | context_id={} error={}", context_id, exc)
            yield ErrorFrame(error=f"TTS error: {exc}")
