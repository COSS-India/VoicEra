"""Orpheus Indic TTS over the model-server OpenAI-compatible ``/v1/audio/speech``."""

from __future__ import annotations

import asyncio
import os
from typing import AsyncGenerator, Optional

import aiohttp
from loguru import logger
from pipecat.frames.frames import (
    ErrorFrame,
    Frame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.services.tts_service import TTSService

from config.tts_mappings import orpheus_voice
from services.ai4bharat.model_server import model_server_url

ORPHEUS_SAMPLE_RATE = 24000


def _sock_read_timeout() -> float:
    try:
        value = float(os.getenv("INDIC_TTS_SOCK_READ_SECS", "30"))
    except ValueError:
        return 30.0
    return value if value > 0 else 30.0


class IndicOrpheusTTSService(TTSService):
    """Stream 24 kHz PCM from Orpheus. The speaker name selects the language."""

    def __init__(
        self,
        *,
        voice: Optional[str] = None,
        language_id: str = "hi",
        style: Optional[str] = None,
        aiohttp_session: Optional[aiohttp.ClientSession] = None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._url = model_server_url("/v1/audio/speech")
        self._language_id = language_id
        self._voice = orpheus_voice(language_id, voice)
        self._style = style.strip() if style else None
        self._session = aiohttp_session
        self._owns_session = aiohttp_session is None
        logger.info("IndicOrpheus TTS initialized | url={} voice={} language={}", self._url, self._voice, language_id)

    def can_generate_metrics(self) -> bool:
        return True

    async def start(self, frame: Frame):
        await super().start(frame)
        if self._session is None:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=None, connect=10, sock_read=_sock_read_timeout())
            )

    async def _close_session(self) -> None:
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None

    async def stop(self, frame: Frame):
        await self._close_session()
        await super().stop(frame)

    async def cancel(self, frame: Frame):
        await self._close_session()
        await super().cancel(frame)

    def set_language(self, language_id: str) -> None:
        """Switch language by switching to a speaker of that language."""
        self._language_id = language_id
        self._voice = orpheus_voice(language_id, self._voice)
        logger.info("IndicOrpheus language -> {} (voice={})", language_id, self._voice)

    async def run_tts(self, text: str) -> AsyncGenerator[Frame, None]:
        if not text.strip():
            return
        if self._session is None:
            yield ErrorFrame("IndicOrpheus TTS session not started")
            return

        payload = {"model": "orpheus", "input": text, "voice": self._voice, "response_format": "pcm"}
        if self._style:
            payload["style"] = self._style

        await self.start_ttfb_metrics()
        yield TTSStartedFrame()
        error: Optional[str] = None
        try:
            async with self._session.post(self._url, json=payload) as resp:
                if resp.status != 200:
                    error = f"IndicOrpheus TTS HTTP {resp.status}: {(await resp.text())[:200]}"
                else:
                    await self.start_tts_usage_metrics(text)
                    carry = b""
                    async for chunk in resp.content.iter_chunked(self.chunk_size):
                        # Keep int16 frames aligned across network chunk boundaries.
                        chunk = carry + chunk
                        cut = len(chunk) - (len(chunk) % 2)
                        carry = chunk[cut:]
                        if cut:
                            await self.stop_ttfb_metrics()
                            yield TTSAudioRawFrame(audio=chunk[:cut], sample_rate=ORPHEUS_SAMPLE_RATE, num_channels=1)
        except asyncio.TimeoutError:
            error = "IndicOrpheus TTS request timeout"
        except aiohttp.ClientError as e:
            error = f"IndicOrpheus TTS connection error: {e}"
        # Not in a finally: the translation room aclose()s a stalled generator,
        # and yielding during that close raises RuntimeError.
        if error:
            yield ErrorFrame(error)
        yield TTSStoppedFrame()
