"""Indic Orpheus TTS — OpenAI-compatible speech client for model-server.

Pipecat's OpenAITTSService hard-rejects non-OpenAI voice names, so this
service mirrors its streaming PCM client without the voice whitelist.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

from loguru import logger
from openai import AsyncOpenAI, BadRequestError
from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.utils.tracing.service_decorators import traced_tts

from apps.providers.runtime_language import update_tts_settings_with_voice_language

from .catalog import DEFAULT_TTS_STYLE, DEFAULT_TTS_VOICE, SAMPLE_RATE


class IndicOrpheusTTSService(TTSService):
    """Stream PCM from model-server Orpheus ``POST /v1/audio/speech``."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str = "orpheus-indic",
        voice: str = DEFAULT_TTS_VOICE,
        style: str | None = DEFAULT_TTS_STYLE,
        sample_rate: int | None = None,
        **kwargs,
    ):
        # API PCM is always 24 kHz. Never inherit the pipeline rate onto frame
        # metadata — a mislabeled rate warps transport resample and recordings.
        if sample_rate is not None and sample_rate != SAMPLE_RATE:
            logger.warning(
                "Indic Orpheus TTS only supports {}Hz; ignoring requested {}Hz",
                SAMPLE_RATE,
                sample_rate,
            )

        super().__init__(
            sample_rate=SAMPLE_RATE,
            push_start_frame=True,
            push_stop_frames=True,
            **kwargs,
        )

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._voice = voice
        self._style = style.strip() if style else None

        logger.info(
            "Indic Orpheus TTS initialized | base_url={} model={} voice={} style={}",
            base_url,
            model,
            voice,
            self._style,
        )

    def can_generate_metrics(self) -> bool:
        return True

    async def _update_settings(self, delta: TTSSettings) -> dict[str, Any]:
        return await update_tts_settings_with_voice_language(
            self, delta, super_update=super()._update_settings
        )

    async def start(self, frame):
        await super().start(frame)
        # Pin after StartFrame — Pipecat may otherwise adopt audio_out_sample_rate.
        self._sample_rate = SAMPLE_RATE

    @traced_tts
    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        if not text.strip():
            return

        if not self._voice:
            yield ErrorFrame(error="Indic Orpheus TTS voice must be specified")
            return

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
                            SAMPLE_RATE,
                            1,
                            context_id=context_id,
                        )
        except BadRequestError as exc:
            logger.error("Indic Orpheus TTS bad request | context_id={} error={}", context_id, exc)
            yield ErrorFrame(error=f"Unknown error occurred: {exc}")
        except Exception as exc:
            logger.error("Indic Orpheus TTS error | context_id={} error={}", context_id, exc)
            yield ErrorFrame(error=f"TTS error: {exc}")
