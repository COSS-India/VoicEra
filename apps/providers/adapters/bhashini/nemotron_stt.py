"""Bhashini NVCF Nemotron Indic gRPC streaming STT for Pipecat."""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator, Optional, Union

import grpc
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

from . import asr_pb2, asr_pb2_grpc
from .catalog import DEFAULT_GRPC_URL

SAMPLE_RATE = 16000
MAX_MSG = 4 * 1024 * 1024
_CHANNEL_OPTS = [
    ("grpc.max_receive_message_length", MAX_MSG),
    ("grpc.max_send_message_length", MAX_MSG),
]

# Outbound queue sentinels (audio is raw bytes).
_COMMIT = object()
_CLOSE = object()


def _strip_bearer(token: str) -> str:
    key = token.strip()
    if key.lower().startswith("bearer "):
        return key[7:].strip()
    return key


class BhashiniNemotronSTTService(STTService):
    """NVCF ``voicera.asr.v1`` StreamingRecognize; Silero commits via ``CommitTurn``.

    Server-side VAD is assumed off. Partials stream while the user speaks; a
    final transcript is requested only on ``VADUserStoppedSpeakingFrame`` —
    matching local ``IndicNemotronSTTService`` ``flush_eos`` and Deepgram Finalize.
    """

    def __init__(
        self,
        *,
        auth_token: str,
        function_id: str,
        grpc_host: str = DEFAULT_GRPC_URL,
        language: str = "hi",
        sample_rate: int | None = None,
        **kwargs,
    ):
        super().__init__(sample_rate=sample_rate, **kwargs)

        self._auth_token = _strip_bearer(auth_token)
        if not self._auth_token:
            raise ValueError("BhashiniNemotronSTTService requires auth_token")

        self._function_id = function_id.strip()
        if not self._function_id:
            raise ValueError("BhashiniNemotronSTTService requires function_id")

        self._grpc_host = (grpc_host or DEFAULT_GRPC_URL).strip()
        self._language = language.strip().lower()
        self._target_sample_rate = SAMPLE_RATE
        self._resampler = create_stream_resampler()

        self._channel: Optional[grpc.aio.Channel] = None
        self._outbound: Optional[asyncio.Queue] = None
        self._receiver_task: Optional[asyncio.Task] = None
        self._flush_lock = asyncio.Lock()
        self._closed = False
        self._ready = asyncio.Event()
        self._flush_event: Optional[asyncio.Event] = None
        self._pending_final: str = ""

        logger.info(
            "Bhashini Nemotron STT initialized | grpc_host={} function_id={} language={}",
            self._grpc_host,
            self._function_id,
            self._language,
        )

    def _metadata(self) -> list[tuple[str, str]]:
        return [
            ("function-id", self._function_id),
            ("authorization", f"Bearer {self._auth_token}"),
        ]

    def _streaming_config(self) -> asr_pb2.StreamingConfig:
        return asr_pb2.StreamingConfig(
            language=self._language,
            sample_rate_hz=SAMPLE_RATE,
            encoding=asr_pb2.LINEAR16,
        )

    async def _enqueue(self, item: Union[bytes, object]) -> None:
        if self._outbound is None:
            raise RuntimeError("Nemotron gRPC stream is not connected")
        await self._outbound.put(item)

    async def _request_generator(self):
        assert self._outbound is not None
        yield asr_pb2.StreamingRequest(config=self._streaming_config())
        while True:
            item = await self._outbound.get()
            if item is _CLOSE:
                return
            if item is _COMMIT:
                yield asr_pb2.StreamingRequest(commit=asr_pb2.CommitTurn())
                continue
            if isinstance(item, asr_pb2.StreamingConfig):
                yield asr_pb2.StreamingRequest(config=item)
                continue
            if isinstance(item, (bytes, bytearray)) and item:
                yield asr_pb2.StreamingRequest(audio=bytes(item))

    async def _connect(self) -> None:
        if self._channel or self._closed:
            return

        logger.info(
            "Connecting to Bhashini Nemotron ASR at {} language={}",
            self._grpc_host,
            self._language,
        )
        self._ready.clear()
        self._outbound = asyncio.Queue()
        credentials = grpc.ssl_channel_credentials()
        self._channel = grpc.aio.secure_channel(
            self._grpc_host,
            credentials,
            options=_CHANNEL_OPTS,
        )
        stub = asr_pb2_grpc.AsrStub(self._channel)
        call = stub.StreamingRecognize(
            self._request_generator(),
            metadata=self._metadata(),
        )
        self._receiver_task = asyncio.create_task(self._receive_handler(call))
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            await self._disconnect()
            raise RuntimeError("Nemotron ASR gRPC session did not become ready")

    async def _disconnect(self) -> None:
        task = self._receiver_task
        self._receiver_task = None
        outbound = self._outbound
        self._outbound = None
        channel = self._channel
        self._channel = None
        self._ready.clear()

        if outbound is not None:
            try:
                await outbound.put(_CLOSE)
            except Exception:
                pass

        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

        if channel is not None:
            try:
                await channel.close()
            except Exception:
                pass

    async def _receive_handler(self, call) -> None:
        try:
            async for resp in call:
                event = resp.WhichOneof("event")
                if event == "started":
                    s = resp.started
                    logger.info(
                        "Bhashini Nemotron session started | session={} chunk_ms={} "
                        "rate={} lang={}",
                        s.session_id,
                        s.model_chunk_ms,
                        s.expected_sample_rate_hz,
                        s.language,
                    )
                    self._ready.set()
                elif event == "transcript":
                    t = resp.transcript
                    text = (t.text or "").strip()
                    if t.is_final:
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
                elif event == "warning":
                    w = resp.warning
                    logger.warning(
                        "Bhashini Nemotron warning | code={} message={} "
                        "samples_dropped={}",
                        w.code,
                        w.message,
                        w.samples_dropped,
                    )
        except asyncio.CancelledError:
            raise
        except grpc.aio.AioRpcError as e:
            if not self._closed:
                logger.error(
                    "Bhashini Nemotron gRPC receive error: {}: {}",
                    e.code(),
                    e.details(),
                )
                await self.push_frame(
                    ErrorFrame(f"Nemotron ASR gRPC failed: {e.code()}: {e.details()}")
                )
        except Exception as e:
            if not self._closed:
                logger.error("Bhashini Nemotron receive error: {}", e)
                await self.push_frame(ErrorFrame(f"Nemotron ASR receive failed: {e}"))
        finally:
            self._ready.clear()
            if self._flush_event is not None:
                self._flush_event.set()
            # Unexpected stream death: drop handles so run_stt can reconnect.
            # Do not call _disconnect() here — that cancels this same task.
            if not self._closed and self._channel is not None:
                channel = self._channel
                self._channel = None
                self._outbound = None
                self._receiver_task = None
                try:
                    await channel.close()
                except Exception:
                    pass

    async def _flush_utterance(self) -> None:
        if not self._channel or self._outbound is None:
            return
        if self._flush_lock.locked():
            return
        async with self._flush_lock:
            self._pending_final = ""
            event = asyncio.Event()
            self._flush_event = event
            try:
                await self._enqueue(_COMMIT)
                try:
                    await asyncio.wait_for(event.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning(
                        "Nemotron CommitTurn timed out waiting for final transcript"
                    )
            finally:
                self._flush_event = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, VADUserStartedSpeakingFrame):
            await self.start_ttfb_metrics()
            await self.start_processing_metrics()
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            # Commit only on Silero VAD stop — same as local Nemotron flush_eos.
            # Do NOT commit on UserStoppedSpeakingFrame (aggregator turn-stop).
            try:
                await self._flush_utterance()
            except Exception as e:
                logger.error("Nemotron CommitTurn on VAD stop failed: {}", e)
                await self.push_frame(ErrorFrame(f"Nemotron commit failed: {e}"))

    async def start(self, frame: StartFrame):
        await super().start(frame)
        self._closed = False
        try:
            await self._connect()
        except Exception as e:
            logger.error("Failed to connect Bhashini Nemotron STT: {}", e)
            await self.push_frame(ErrorFrame(f"Nemotron STT connect failed: {e}"))

    async def stop(self, frame: EndFrame):
        # Facade half-close sends flush_eos — wait for that final, then tear down.
        # Do not CommitTurn first or the last turn is finalised twice.
        self._closed = True
        try:
            if self._channel and self._outbound is not None:
                event = asyncio.Event()
                self._flush_event = event
                try:
                    await self._enqueue(_CLOSE)
                    self._outbound = None
                    await asyncio.wait_for(event.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logger.warning(
                        "Nemotron half-close timed out waiting for final transcript"
                    )
                except Exception as e:
                    logger.debug("Nemotron stop half-close: {}", e)
                finally:
                    self._flush_event = None
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

        if not self._channel:
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
            await self._enqueue(outgoing)
        except Exception as e:
            logger.error("Nemotron STT send error: {}", e)
            yield ErrorFrame(f"Nemotron STT send failed: {e}")
            return

        yield None

    async def set_language(self, language: str):
        wire = language.strip().lower()
        logger.info("Switching Bhashini Nemotron language to: {}", wire)
        self._language = wire
        if self._channel and self._outbound is not None:
            await self._enqueue(self._streaming_config())

    def can_generate_metrics(self) -> bool:
        return True
