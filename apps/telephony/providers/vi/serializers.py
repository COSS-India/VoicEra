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
from pipecat.audio.utils import create_stream_resampler
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
        self._input_resampler = create_stream_resampler()
        self._output_resampler = create_stream_resampler()
        self._exit_sent = False
        self._stop_received = False
        self._playout_deadline = time.monotonic()
        self._final_mark_event = asyncio.Event()

    async def setup(self, frame: StartFrame):
        self._sample_rate = self._params.sample_rate or frame.audio_in_sample_rate
        self._stream_start_time = time.monotonic()
        self._playout_deadline = time.monotonic()

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

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, InterruptionFrame):
            self._output_buffer.clear()
            return json.dumps(
                {
                    "event": "clear",
                    "sequence_number": self._next_sequence(),
                    "room_id": self._room_id,
                }
            )

        if isinstance(frame, (EndFrame, CancelFrame)):
            if self._exit_sent:
                return None
            self._exit_sent = True
            messages: list[str] = []
            while True:
                chunk = self._take_output_chunk(force=True)
                if not chunk:
                    break
                messages.append(json.dumps(self._build_media_message(chunk)))

            messages.append(
                json.dumps(
                    {
                        "event": "mark",
                        "sequence_number": self._next_sequence(),
                        "room_id": self._room_id,
                        "mark": {"name": FINAL_MARK_NAME},
                    }
                )
            )

            remaining = max(0.0, self._playout_deadline - time.monotonic())
            wait_secs = min(remaining + DRAIN_GRACE_SECS, MAX_DRAIN_SECS)
            if wait_secs > 0 and not self._stop_received:
                try:
                    await asyncio.wait_for(
                        self._final_mark_event.wait(), timeout=wait_secs
                    )
                except asyncio.TimeoutError:
                    logger.debug("VI final mark wait timed out after {:.1f}s", wait_secs)

            if self._params.auto_exit:
                messages.append(
                    json.dumps(
                        {
                            "event": "exit",
                            "sequence_number": self._next_sequence(),
                            "room_id": self._room_id,
                            "parameters": self._params.exit_parameters or {},
                        }
                    )
                )
            return "\n".join(messages) if messages else None

        if isinstance(frame, AudioRawFrame):
            audio = frame.audio
            if frame.sample_rate and frame.sample_rate != VI_SAMPLE_RATE:
                audio = await self._output_resampler.resample(
                    audio, frame.sample_rate, VI_SAMPLE_RATE
                )
            self._output_buffer.extend(audio)
            chunk = self._take_output_chunk(force=False)
            if not chunk:
                return None
            return json.dumps(self._build_media_message(chunk))

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
            self._stop_received = True
            self._final_mark_event.set()
            return EndFrame()

        if event == "mark":
            name = (message.get("mark") or {}).get("name")
            if name == FINAL_MARK_NAME:
                self._final_mark_event.set()
            return None

        return None
