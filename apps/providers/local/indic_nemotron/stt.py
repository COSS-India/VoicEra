"""Indic Nemotron native WebSocket STT service for Pipecat."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator, Optional
from urllib.parse import urlencode

from loguru import logger
from pipecat.audio.utils import create_stream_resampler
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    InterimTranscriptionFrame,
    StartFrame,
    TranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection
from pipecat.services.stt_service import STTService
from pipecat.utils.time import time_now_iso8601

try:
    import websockets
except ModuleNotFoundError as e:
    logger.error("Exception: {}", e)
    logger.error("Install with: pip install websockets")
    raise Exception(f"Missing module: {e}") from e

from .catalog import SAMPLE_RATE


class IndicNemotronSTTService(STTService):
    """Stream PCM to model-server ``/v1/asr/ws``; Silero commits turns via ``flush_eos``.

    Server-side VAD is left off (``NEMOTRON_VAD=0``). Partials stream while the
    user speaks; a final transcript is requested only on
    ``VADUserStoppedSpeakingFrame`` — matching Deepgram ``Finalize`` and
    ``OpenAIRealtimeSTTService(turn_detection=False)`` buffer commit.
    """

    def __init__(
        self,
        *,
        ws_url: str,
        language: str = "hi",
        sample_rate: int | None = None,
        **kwargs,
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)

        self._ws_url = ws_url.rstrip("/")
        self._language = language.strip().lower()
        self._target_sample_rate = SAMPLE_RATE
        self._resampler = create_stream_resampler()

        self._websocket = None
        self._receiver_task: Optional[asyncio.Task] = None
        self._send_lock = asyncio.Lock()
        self._flush_lock = asyncio.Lock()
        self._closed = False
        self._ready = asyncio.Event()
        self._flush_event: Optional[asyncio.Event] = None
        self._pending_final: str = ""

        logger.info(
            "Indic Nemotron STT initialized | ws_url={} language={}",
            self._ws_url,
            self._language,
        )

    def _connection_url(self) -> str:
        sep = "&" if "?" in self._ws_url else "?"
        return f"{self._ws_url}{sep}{urlencode({'language': self._language})}"

    async def _send_json(self, payload: dict) -> None:
        if not self._websocket:
            raise RuntimeError("Nemotron websocket is not connected")
        async with self._send_lock:
            await self._websocket.send(json.dumps(payload))

    async def _send_pcm(self, pcm: bytes) -> None:
        if not self._websocket or not pcm:
            return
        async with self._send_lock:
            await self._websocket.send(pcm)

    async def _connect(self) -> None:
        if self._websocket or self._closed:
            return

        uri = self._connection_url()
        logger.info("Connecting to Indic Nemotron ASR at {}", uri)
        self._ready.clear()
        self._websocket = await websockets.connect(uri, ping_interval=20, ping_timeout=20)
        self._receiver_task = asyncio.create_task(self._receive_handler())
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            await self._disconnect()
            raise RuntimeError("Nemotron ASR websocket did not become ready")

    async def _disconnect(self) -> None:
        task = self._receiver_task
        self._receiver_task = None
        ws = self._websocket
        self._websocket = None
        self._ready.clear()

        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass

    async def _receive_handler(self) -> None:
        assert self._websocket is not None
        try:
            async for message in self._websocket:
                if isinstance(message, (bytes, bytearray)):
                    continue
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    logger.debug("Nemotron sent non-JSON message: {}", message)
                    continue

                if "error" in data and "text" not in data:
                    logger.error("Nemotron ASR error: {}", data["error"])
                    await self.push_frame(ErrorFrame(f"Nemotron ASR error: {data['error']}"))
                    continue

                status = data.get("status")
                if status == "ready":
                    self._ready.set()
                    continue
                if status in (
                    "hello_ack",
                    "sample_rate_mismatch",
                    "language_updated",
                    "language_rejected",
                    "session_reset",
                    "audio_rate_warning",
                    "language_detected",
                ):
                    if status == "language_rejected":
                        logger.error(
                            "Nemotron rejected language {}: {}",
                            data.get("language"),
                            data.get("error"),
                        )
                    elif status == "audio_rate_warning":
                        logger.warning(
                            "Nemotron audio rate warning | ratio={} implied={}",
                            data.get("ratio"),
                            data.get("implied_sample_rate"),
                        )
                    continue

                text = str(data.get("text") or "").strip()
                if not text and "is_final" not in data:
                    continue

                is_final = bool(data.get("is_final", False))
                if is_final:
                    self._pending_final = text
                    if self._flush_event is not None:
                        self._flush_event.set()
                    if text:
                        await self.stop_ttfb_metrics()
                        await self.push_frame(
                            TranscriptionFrame(
                                text=text,
                                user_id="",
                                timestamp=time_now_iso8601(),
                            )
                        )
                        await self.stop_processing_metrics()
                elif text:
                    await self.stop_ttfb_metrics()
                    await self.push_frame(
                        InterimTranscriptionFrame(
                            text=text,
                            user_id="",
                            timestamp=time_now_iso8601(),
                        )
                    )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if not self._closed:
                logger.error("Nemotron ASR receive error: {}", e)
                await self.push_frame(ErrorFrame(f"Nemotron ASR receive failed: {e}"))
        finally:
            self._ready.clear()
            if self._flush_event is not None:
                self._flush_event.set()

    async def _flush_utterance(self) -> None:
        if not self._websocket:
            return
        if self._flush_lock.locked():
            return
        async with self._flush_lock:
            self._pending_final = ""
            event = asyncio.Event()
            self._flush_event = event
            try:
                await self._send_json({"action": "flush_eos"})
                try:
                    await asyncio.wait_for(event.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning("Nemotron flush_eos timed out waiting for final transcript")
            finally:
                self._flush_event = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, VADUserStartedSpeakingFrame):
            await self.start_ttfb_metrics()
            await self.start_processing_metrics()
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            # Commit only on Silero VAD stop — same as Deepgram Finalize and
            # OpenAIRealtimeSTTService(turn_detection=False) commit.
            # Do NOT flush on UserStoppedSpeakingFrame: that is the aggregator's
            # turn-stop after a final was already consumed; flushing again
            # re-emits a short final and starts another turn (interrupt loop).
            try:
                await self._flush_utterance()
            except Exception as e:
                logger.error("Nemotron flush on VAD stop failed: {}", e)
                await self.push_frame(ErrorFrame(f"Nemotron flush failed: {e}"))

    async def start(self, frame: StartFrame):
        await super().start(frame)
        self._closed = False
        try:
            await self._connect()
        except Exception as e:
            logger.error("Failed to connect Indic Nemotron STT: {}", e)
            await self.push_frame(ErrorFrame(f"Nemotron STT connect failed: {e}"))

    async def stop(self, frame: EndFrame):
        self._closed = True
        try:
            if self._websocket:
                await self._flush_utterance()
        finally:
            await self._disconnect()
            await super().stop(frame)

    async def cancel(self, frame: CancelFrame):
        self._closed = True
        await self._disconnect()
        await super().cancel(frame)

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        if not audio or self._closed:
            return

        if not self._websocket:
            try:
                await self._connect()
            except Exception as e:
                yield ErrorFrame(f"Nemotron STT connect failed: {e}")
                return

        outgoing = audio
        pipeline_rate = self.sample_rate or self._target_sample_rate
        if pipeline_rate != self._target_sample_rate:
            outgoing = await self._resampler.resample(
                audio, pipeline_rate, self._target_sample_rate
            )
        if not outgoing:
            return

        try:
            await self._send_pcm(outgoing)
        except Exception as e:
            logger.error("Nemotron STT send error: {}", e)
            yield ErrorFrame(f"Nemotron STT send failed: {e}")
            return

        yield None

    async def set_language(self, language: str):
        wire = language.strip().lower()
        logger.info("Switching Indic Nemotron language to: {}", wire)
        self._language = wire
        if self._websocket:
            await self._send_json({"action": "set_language", "language": wire})

    def can_generate_metrics(self) -> bool:
        return True
