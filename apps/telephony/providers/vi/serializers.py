"""Vodafone Idea (VI) Voice Streaming WebSocket serializer."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Optional

from loguru import logger
from pydantic import Field
from pipecat.audio.dtmf.types import KeypadEntry
from pipecat.audio.utils import create_file_resampler, create_stream_resampler
from pipecat.frames.frames import (
    AudioRawFrame,
    CancelFrame,
    EndFrame,
    Frame,
    InputAudioRawFrame,
    InputDTMFFrame,
    InterruptionFrame,
    StartFrame,
)
from pipecat.serializers.base_serializer import FrameSerializer

VI_SAMPLE_RATE = 8000
MIN_CHUNK_BYTES = 1600  # ~100 ms at 8 kHz mono 16-bit
MAX_CHUNK_BYTES = 51200  # 50 KB
CHUNK_ALIGN_BYTES = 160  # 10 ms of audio
BYTES_PER_SECOND = VI_SAMPLE_RATE * 2

FINAL_MARK_NAME = "voicera-final"
MAX_DRAIN_SECS = 30.0
DRAIN_GRACE_SECS = 2.0


class ViFrameSerializer(FrameSerializer):
    """Serializer for Vodafone Idea bidirectional Voice Streaming protocol."""

    class InputParams(FrameSerializer.InputParams):
        sample_rate: Optional[int] = None
        auto_exit: bool = True
        exit_parameters: dict = Field(default_factory=dict)

    def __init__(
        self,
        room_id: str,
        call_id: str,
        websocket=None,
        params: Optional[InputParams] = None,
    ):
        super().__init__(params or ViFrameSerializer.InputParams())
        self._sample_rate = self._params.sample_rate or VI_SAMPLE_RATE
        self._room_id = room_id
        self._call_id = call_id
        self._websocket = websocket
        self._sequence_number = 0
        self._media_chunk_index = 0
        self._stream_start_time = time.monotonic()
        self._output_buffer = bytearray()
        # Inbound mic: stream resampler (continuous, low-latency).
        self._input_resampler = create_stream_resampler()
        # Outbound wire: file/batch resampler. SOXRStreamAudioResampler often
        # returns empty mid-utterance while priming/batching; serialize()→None
        # then makes pipecat-ai==1.8.1 MediaSender skip push_downstream, so
        # AudioBufferProcessor after transport.output() loses bot frames.
        # create_file_resampler() yields proportional PCM every chunk.
        self._output_resampler = create_file_resampler()
        self._exit_sent = False
        self._stop_received = False
        self._playout_deadline = time.monotonic()
        self._pace_deadline = time.monotonic()
        self._final_mark_event = asyncio.Event()

    async def setup(self, frame: StartFrame):
        self._sample_rate = self._params.sample_rate or frame.audio_in_sample_rate
        self._stream_start_time = time.monotonic()
        self._playout_deadline = time.monotonic()
        self._pace_deadline = time.monotonic()

    def set_exit_parameters(self, parameters: dict) -> None:
        self._params.exit_parameters = dict(parameters or {})

    def _next_sequence(self) -> int:
        self._sequence_number += 1
        return self._sequence_number

    def _timestamp_ms(self) -> str:
        elapsed_ms = int((time.monotonic() - self._stream_start_time) * 1000)
        return str(max(elapsed_ms, 0))

    @staticmethod
    def _align_down(size: int) -> int:
        if size <= 0:
            return 0
        return size - (size % CHUNK_ALIGN_BYTES)

    def _take_output_chunk(self, force: bool = False) -> Optional[bytes]:
        aligned_len = self._align_down(len(self._output_buffer))
        if aligned_len < MIN_CHUNK_BYTES and not force:
            return None
        if aligned_len <= 0 and not force:
            return None

        chunk_len = self._align_down(min(aligned_len, MAX_CHUNK_BYTES))
        if chunk_len < MIN_CHUNK_BYTES:
            if not force or not self._output_buffer:
                return None
            self._output_buffer.extend(
                b"\x00" * (MIN_CHUNK_BYTES - len(self._output_buffer))
            )
            chunk_len = MIN_CHUNK_BYTES

        chunk = bytes(self._output_buffer[:chunk_len])
        del self._output_buffer[:chunk_len]
        return chunk

    def _track_playout(self, pcm_bytes: int) -> None:
        duration = pcm_bytes / BYTES_PER_SECOND
        self._playout_deadline = max(time.monotonic(), self._playout_deadline) + duration

    def _advance_pace(self, pcm_bytes: int) -> None:
        duration = pcm_bytes / BYTES_PER_SECOND
        if duration <= 0:
            return
        now = time.monotonic()
        self._pace_deadline = max(now, self._pace_deadline) + duration

    async def _pace(self, pcm_bytes: int) -> None:
        """Realtime clock for buffered frames (transport skips sleep when we return None)."""
        now = time.monotonic()
        wait = self._pace_deadline - now
        if wait > 0:
            await asyncio.sleep(wait)
        self._advance_pace(pcm_bytes)

    def _build_media_message(self, pcm_data: bytes) -> dict:
        self._media_chunk_index += 1
        self._track_playout(len(pcm_data))
        return {
            "event": "media",
            "sequence_number": self._next_sequence(),
            "room_id": self._room_id,
            "media": {
                "track": "outbound",
                "chunk": self._media_chunk_index,
                "timestamp": self._timestamp_ms(),
                "payload": base64.b64encode(pcm_data).decode("utf-8"),
            },
        }

    def _build_mark_message(self, name: str) -> dict:
        return {
            "event": "mark",
            "sequence_number": self._next_sequence(),
            "room_id": self._room_id,
            "mark": {"name": name},
        }

    def _build_clear_message(self) -> dict:
        return {
            "event": "clear",
            "sequence_number": self._next_sequence(),
            "room_id": self._room_id,
        }

    def _build_exit_message(self) -> dict:
        return {
            "event": "exit",
            "sequence_number": self._next_sequence(),
            "room_id": self._room_id,
            "exit": {"parameters": dict(self._params.exit_parameters)},
        }

    async def _send_out_of_band(self, message: dict) -> None:
        if self._websocket is None:
            return
        try:
            await self._websocket.send_text(json.dumps(message))
        except Exception as exc:
            logger.debug("VI out-of-band send failed: {}", exc)

    async def _wait_for_playback(self) -> None:
        remaining = max(0.0, self._playout_deadline - time.monotonic())
        timeout = min(remaining + DRAIN_GRACE_SECS, MAX_DRAIN_SECS)
        try:
            await asyncio.wait_for(self._final_mark_event.wait(), timeout=timeout)
            logger.debug("VI confirmed final playback via mark")
        except asyncio.TimeoutError:
            logger.warning(
                "VI did not acknowledge final mark within {:.1f}s; exiting anyway",
                timeout,
            )

    async def _drain_and_exit(self) -> str:
        self._exit_sent = True
        tail = self._take_output_chunk(force=True)
        if tail:
            await self._send_out_of_band(self._build_media_message(tail))
        if self._websocket is not None:
            await self._send_out_of_band(self._build_mark_message(FINAL_MARK_NAME))
            await self._wait_for_playback()
        return json.dumps(self._build_exit_message())

    async def _resample_to_vi_rate(self, audio: bytes, sample_rate: int) -> bytes:
        if sample_rate == VI_SAMPLE_RATE:
            return audio
        return await self._output_resampler.resample(audio, sample_rate, VI_SAMPLE_RATE)

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, InterruptionFrame):
            self._output_buffer.clear()
            now = time.monotonic()
            self._playout_deadline = now
            self._pace_deadline = now
            return json.dumps(self._build_clear_message())

        if isinstance(frame, (EndFrame, CancelFrame)):
            if self._exit_sent or not self._params.auto_exit:
                return None
            if self._stop_received:
                self._exit_sent = True
                self._output_buffer.clear()
                return None
            return await self._drain_and_exit()

        if isinstance(frame, AudioRawFrame):
            data = await self._resample_to_vi_rate(frame.audio, frame.sample_rate)
            if not data:
                return None
            self._output_buffer.extend(data)
            # Prefer ~100 ms aggregates (MIN_CHUNK_BYTES). If still short, emit any
            # frame-aligned PCM without silence-padding.
            #
            # Why: pipecat-ai==1.8.1 FastAPIWebsocketOutputTransport treats
            # serialize()→None as write failure and MediaSender then skips
            # push_downstream — AudioBufferProcessor after transport.output()
            # would miss most bot frames (sounds ~2–3× fast). Stock Pipecat has
            # no hook for "accepted but buffered"; returning a real payload is
            # the smallest fix that keeps FastAPIWebsocketTransport unchanged.
            chunk = self._take_output_chunk(force=False)
            if not chunk:
                aligned = self._align_down(len(self._output_buffer))
                if aligned >= CHUNK_ALIGN_BYTES:
                    chunk = bytes(self._output_buffer[:aligned])
                    del self._output_buffer[:aligned]
            if chunk:
                # Transport sleeps on successful writes; only advance our clock.
                self._advance_pace(len(data))
                return json.dumps(self._build_media_message(chunk))
            # Sub-ALIGN remainder only (< 10 ms). MediaSender chunks are typically
            # ≥40 ms, so after file-resample this path is rare; bytes stay in
            # _output_buffer and ride the next frame or EndFrame force-drain.
            # Returning None here still drops that one MediaSender frame from
            # AudioBuffer (1.8.1 contract) — acceptable for <10 ms tails only.
            await self._pace(len(data))
            return None

        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        try:
            message = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None

        event = message.get("event")
        if event in ("connected", "start"):
            return None

        if event == "media":
            media = message.get("media") or {}
            payload = media.get("payload")
            if not payload:
                return None
            try:
                pcm = base64.b64decode(payload)
            except Exception:
                return None
            if not pcm:
                return None
            if self._sample_rate and self._sample_rate != VI_SAMPLE_RATE:
                pcm = await self._input_resampler.resample(
                    pcm, VI_SAMPLE_RATE, self._sample_rate
                )
            return InputAudioRawFrame(
                audio=pcm,
                sample_rate=self._sample_rate or VI_SAMPLE_RATE,
                num_channels=1,
            )

        if event == "dtmf":
            digit = (message.get("dtmf") or {}).get("digit") or message.get("digit")
            if not digit:
                return None
            try:
                return InputDTMFFrame(KeypadEntry(str(digit)))
            except Exception:
                return None

        if event == "clear":
            return InterruptionFrame()

        if event == "stop":
            reason = (message.get("stop") or {}).get("reason", "")
            logger.info("VI stop event received (reason={})", reason)
            self._stop_received = True
            self._final_mark_event.set()
            return EndFrame()

        if event == "mark":
            name = (message.get("mark") or {}).get("name")
            if name == FINAL_MARK_NAME:
                self._final_mark_event.set()
            return None

        return None
