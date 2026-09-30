"""IndicNemotron streaming STT over the model-server ``/v1/asr/ws`` websocket.

The server runs with its own VAD off, so it never ends an utterance by itself:
partials stream while audio flows and a final is produced only when we send
``flush_eos``. The pipeline's Silero VAD decides when that happens.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import AsyncGenerator, Optional
from urllib.parse import urlencode

import websockets
from loguru import logger
from pipecat.audio.utils import create_stream_resampler
from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
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

from services.ai4bharat.model_server import model_server_url

NEMOTRON_SAMPLE_RATE = 16000
_FLUSH_TIMEOUT_SECS = 5.0
_CONNECT_TIMEOUT_SECS = 5.0
_RECONNECT_BACKOFF_SECS = 5.0


def _max_utterance_bytes() -> int:
    """Speech sent without a VAD stop before we force a final anyway.

    Without a cap, a presenter who never pauses long enough for VAD produces
    only partials and nothing downstream ever gets text to act on.
    """
    try:
        secs = float(os.getenv("INDIC_NEMOTRON_MAX_UTTERANCE_SECS", "15"))
    except ValueError:
        secs = 15.0
    return int(max(secs, 1.0) * NEMOTRON_SAMPLE_RATE) * 2


class IndicNemotronSTTService(STTService):
    """Stream PCM to IndicNemotron and emit interim/final transcripts."""

    def __init__(self, *, language: str = "hi", sample_rate: Optional[int] = None, **kwargs):
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._ws_url = model_server_url("/v1/asr/ws", websocket=True)
        self._language = language.strip().lower()
        self._resampler = create_stream_resampler()
        self._max_utterance_bytes = _max_utterance_bytes()

        self._websocket = None
        self._receiver_task: Optional[asyncio.Task] = None
        self._ready = asyncio.Event()
        self._flush_lock = asyncio.Lock()
        self._flush_event: Optional[asyncio.Event] = None
        self._speaking = False
        self._utterance_bytes = 0
        self._last_connect_failure = 0.0
        self._closed = False

        logger.info("IndicNemotron STT initialized | url={} language={}", self._ws_url, self._language)

    def can_generate_metrics(self) -> bool:
        return True

    # -- connection ---------------------------------------------------------

    async def _connect(self) -> None:
        if self._websocket or self._closed:
            return
        uri = f"{self._ws_url}?{urlencode({'language': self._language})}"
        self._ready.clear()
        self._websocket = await websockets.connect(
            uri, open_timeout=_CONNECT_TIMEOUT_SECS, ping_interval=20, ping_timeout=20
        )
        self._receiver_task = asyncio.create_task(self._receive_loop(self._websocket))
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=_CONNECT_TIMEOUT_SECS)
        except asyncio.TimeoutError:
            await self._disconnect()
            raise RuntimeError("IndicNemotron websocket did not become ready")

    async def _ensure_connected(self) -> bool:
        if self._websocket:
            return True
        # One failed connect must not turn into a blocking attempt per audio chunk.
        if time.monotonic() - self._last_connect_failure < _RECONNECT_BACKOFF_SECS:
            return False
        try:
            await self._connect()
            return self._websocket is not None
        except Exception as e:
            self._last_connect_failure = time.monotonic()
            logger.error("IndicNemotron connect failed: {}", e)
            await self.push_error(f"IndicNemotron STT connect failed: {e}")
            return False

    async def _disconnect(self) -> None:
        task, self._receiver_task = self._receiver_task, None
        ws, self._websocket = self._websocket, None
        self._ready.clear()
        if task and not task.done() and task is not asyncio.current_task():
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

    async def _receive_loop(self, ws) -> None:
        try:
            async for message in ws:
                if isinstance(message, (bytes, bytearray)):
                    continue
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    continue

                if data.get("status") == "ready":
                    self._ready.set()
                    continue
                if data.get("status") == "language_rejected":
                    logger.error("IndicNemotron rejected language {}: {}", data.get("language"), data.get("error"))
                    continue
                if "status" in data:
                    continue
                if "error" in data and "text" not in data:
                    logger.error("IndicNemotron error: {}", data["error"])
                    continue

                text = str(data.get("text") or "").strip()
                if data.get("is_final"):
                    # Push before waking the flusher: whoever waits on the flush
                    # (the VAD-stop handler) forwards the stop frame next, and
                    # downstream must see this transcript ahead of it.
                    if text:
                        await self.stop_ttfb_metrics()
                        await self.push_frame(
                            TranscriptionFrame(text=text, user_id=self._user_id, timestamp=time_now_iso8601())
                        )
                        await self.stop_processing_metrics()
                    if self._flush_event is not None:
                        self._flush_event.set()
                elif text:
                    await self.stop_ttfb_metrics()
                    await self.push_frame(
                        InterimTranscriptionFrame(text=text, user_id=self._user_id, timestamp=time_now_iso8601())
                    )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if not self._closed:
                logger.error("IndicNemotron receive error: {}", e)
        finally:
            if self._flush_event is not None:
                self._flush_event.set()
            # Dropped by the server: clear it so the next audio chunk reconnects.
            if self._websocket is ws:
                self._websocket = None
                self._ready.clear()

    # -- utterance commit ---------------------------------------------------

    async def _flush(self) -> None:
        """Ask for the final of the current utterance and wait until it is pushed."""
        if not self._websocket:
            return
        if self._flush_lock.locked():
            # A flush is already in flight for this utterance; wait for its final.
            async with self._flush_lock:
                return
        async with self._flush_lock:
            self._utterance_bytes = 0
            self._flush_event = asyncio.Event()
            try:
                await self._websocket.send(json.dumps({"action": "flush_eos"}))
                await asyncio.wait_for(self._flush_event.wait(), timeout=_FLUSH_TIMEOUT_SECS)
            except asyncio.TimeoutError:
                logger.warning("IndicNemotron flush_eos timed out")
            except Exception as e:
                logger.error("IndicNemotron flush failed: {}", e)
            finally:
                self._flush_event = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._speaking = True
            self._utterance_bytes = 0
            await self.start_ttfb_metrics()
            await self.start_processing_metrics()
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self._speaking = False
            # Flush before the base class forwards the stop frame, so the final
            # transcript reaches downstream processors ahead of the turn end.
            await self._flush()
        await super().process_frame(frame, direction)

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        if not audio or self._closed or not await self._ensure_connected():
            return
        if self.sample_rate != NEMOTRON_SAMPLE_RATE:
            audio = await self._resampler.resample(audio, self.sample_rate, NEMOTRON_SAMPLE_RATE)
        if not audio:
            return
        try:
            await self._websocket.send(audio)
        except Exception as e:
            logger.error("IndicNemotron send failed: {}", e)
            await self._disconnect()
            return
        # Only speech counts toward the cap: silence before a VAD start must not
        # make the forced final cut the next utterance short.
        if self._speaking:
            self._utterance_bytes += len(audio)
        if self._utterance_bytes >= self._max_utterance_bytes:
            self._utterance_bytes = 0
            self.create_task(self._flush())
        yield None

    async def set_language(self, language: str) -> None:
        self._language = str(language).strip().lower()
        logger.info("IndicNemotron language -> {}", self._language)
        if self._websocket:
            try:
                await self._websocket.send(json.dumps({"action": "set_language", "language": self._language}))
            except Exception as e:
                # The next connect sends the new language in its URL anyway.
                logger.warning("IndicNemotron set_language send failed: {}", e)

    # -- lifecycle ----------------------------------------------------------

    async def start(self, frame: StartFrame):
        await super().start(frame)
        self._closed = False
        await self._ensure_connected()

    async def stop(self, frame: EndFrame):
        try:
            await self._flush()
        finally:
            self._closed = True
            await self._disconnect()
            await super().stop(frame)

    async def cancel(self, frame: CancelFrame):
        self._closed = True
        await self._disconnect()
        await super().cancel(frame)
