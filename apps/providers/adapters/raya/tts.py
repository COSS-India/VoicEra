"""Raya Bakbak SSE streaming TTS service for Pipecat 1.8.1."""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import numpy as np
from loguru import logger
from pipecat.frames.frames import ErrorFrame, Frame, TTSAudioRawFrame
from pipecat.services.settings import TTSSettings
from pipecat.services.tts_service import TTSService
from pipecat.utils.tracing.service_decorators import traced_tts

from apps.providers.runtime_language import update_tts_settings_with_voice_language

from .catalog import (
    DEFAULT_TTS_SAMPLE_RATE,
    DEFAULT_TTS_VOICE,
    resolve_tts_base_url,
    resolve_voice_id,
)


class RayaTTSService(TTSService):
    """Stream PCM from Raya ``POST /v1/text-to-speech/stream`` (Cartesia-shaped SSE)."""

    def __init__(
        self,
        *,
        api_key: str,
        voice: str = DEFAULT_TTS_VOICE,
        model: str = "standard",
        language: str = "hi",
        speed: float = 1.0,
        sample_rate: int | None = None,
        base_url: str | None = None,
        **kwargs,
    ):
        rate = sample_rate if sample_rate is not None else DEFAULT_TTS_SAMPLE_RATE
        super().__init__(
            sample_rate=rate,
            push_start_frame=True,
            push_stop_frames=True,
            **kwargs,
        )

        self._api_key = api_key.strip()
        if not self._api_key:
            raise ValueError("RayaTTSService requires api_key")

        self._base_url = resolve_tts_base_url(base_url)
        self._voice = voice.strip()
        self._model = model.strip()
        self._language = language
        self._speed = speed
        self._client: httpx.AsyncClient | None = None

        logger.info(
            "Raya TTS initialized | base_url={} model={} language={} voice={}",
            self._base_url,
            self._model,
            self._language,
            self._voice,
        )

    def can_generate_metrics(self) -> bool:
        return True

    async def _update_settings(self, delta: TTSSettings) -> dict[str, Any]:
        return await update_tts_settings_with_voice_language(
            self, delta, super_update=super()._update_settings
        )

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
        return self._client

    async def cleanup(self):
        await super().cleanup()
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    @staticmethod
    def _f32le_to_pcm16(raw: bytes) -> bytes:
        if not raw:
            return b""
        arr = np.frombuffer(raw, dtype=np.float32)
        return (np.clip(arr, -1.0, 1.0) * 32767.0).astype(np.int16).tobytes()

    def _stream_url(self) -> str:
        return f"{self._base_url}/v1/text-to-speech/stream"

    def _payload(self, text: str) -> dict[str, Any]:
        return {
            "text": text,
            "voice_id": resolve_voice_id(self._model, self._language, self._voice),
            "model": self._model,
            "language": self._language,
            "sample_rate": self.sample_rate or DEFAULT_TTS_SAMPLE_RATE,
            "speed": self._speed,
        }

    @traced_tts
    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame | None, None]:
        if not text.strip():
            return

        if not self._voice:
            yield ErrorFrame(error="Raya TTS voice_id must be specified")
            return

        headers = {
            "X-API-Key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        payload = self._payload(text)

        try:
            await self.start_ttfb_metrics()
            client = await self._get_client()
            first_chunk = True

            async with client.stream(
                "POST",
                self._stream_url(),
                headers=headers,
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    error = (await response.aread()).decode("utf-8", errors="replace")
                    logger.error(
                        "Raya TTS HTTP error | status={} error={}",
                        response.status_code,
                        error,
                    )
                    yield ErrorFrame(
                        error=(
                            f"Raya TTS error (status: {response.status_code}, "
                            f"error: {error})"
                        )
                    )
                    return

                await self.start_tts_usage_metrics(text)

                event_name = "message"
                async for line in response.aiter_lines():
                    if line is None:
                        continue
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("event:"):
                        event_name = line[len("event:") :].strip()
                        continue
                    if not line.startswith("data:"):
                        continue

                    data_str = line[len("data:") :].strip()
                    if not data_str:
                        continue

                    try:
                        msg = json.loads(data_str)
                    except json.JSONDecodeError:
                        logger.warning("Raya TTS invalid SSE JSON: {}", data_str[:200])
                        continue

                    msg_type = msg.get("type") or event_name
                    if msg_type == "done" or msg.get("done") is True:
                        break

                    if msg_type != "chunk":
                        continue

                    b64 = msg.get("data") or ""
                    if not b64:
                        continue

                    try:
                        pcm16 = self._f32le_to_pcm16(base64.b64decode(b64))
                    except Exception as e:
                        logger.error("Raya TTS decode error: {}", e)
                        yield ErrorFrame(error=f"Raya TTS audio decode failed: {e}")
                        return

                    if not pcm16:
                        continue

                    if first_chunk:
                        await self.stop_ttfb_metrics()
                        first_chunk = False

                    yield TTSAudioRawFrame(
                        audio=pcm16,
                        sample_rate=self.sample_rate,
                        num_channels=1,
                        context_id=context_id,
                    )

        except Exception as e:
            logger.error("Raya TTS error | context_id={} error={}", context_id, e)
            yield ErrorFrame(error=f"Raya TTS error: {e}")
        finally:
            await self.stop_ttfb_metrics()
