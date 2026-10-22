"""Go To Market WebSocket frame serializer (requires pipecat).

Spec: go2market Audio Streaming Integration Guide v2.0
- Wire: G.711 µ-law, 8000 Hz, 8-bit (audio/x-mulaw)
- Inbound JSON events: connected, start, media, stop, dtmf, mark
- Outbound JSON events: media, mark, clear
"""

from __future__ import annotations

import base64
import json
import time
from typing import Optional

_DEBUG_LOG_PATH = (
    "/home/kowshik/voice_era_repos/voicera-merging/voicERA/.cursor/debug-77bfe8.log"
)

from loguru import logger
from pipecat.audio.dtmf.types import KeypadEntry
from pipecat.audio.utils import create_file_resampler
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

from .audio_codec import decode_wire_mulaw, encode_wire_mulaw
from .stream_protocol import resolve_stream_sid
from .wire import (
    MULAW_FRAME_BYTES,
    MULAW_MAX_SEND_BYTES,
    MULAW_PREFERRED_SEND_BYTES,
    WIRE_SAMPLE_RATE,
    align_mulaw_buffer,
    pad_mulaw_to_frame,
)

# Bumped when wire/serializer behavior changes — visible in runtime logs after rebuild.
GO2MARKET_SERIALIZER_BUILD = "20261022-drain4000"

class Go2MarketFrameSerializer(FrameSerializer):
    """go2market bi-directional streaming (µ-law 8 kHz on the wire)."""

    class InputParams(FrameSerializer.InputParams):
        """``pipeline_sample_rate``: PCM rate inside Pipecat (STT/TTS/VAD)."""

        pipeline_sample_rate: Optional[int] = None

    def __init__(
        self,
        stream_sid: str,
        call_sid: Optional[str] = None,
        websocket=None,
        params: Optional[InputParams] = None,
    ):
        super().__init__(params or Go2MarketFrameSerializer.InputParams())
        self._stream_sid = (stream_sid or "").strip()
        self._call_sid = call_sid
        self._websocket = websocket
        self._pipeline_rate = int(
            self._params.pipeline_sample_rate or WIRE_SAMPLE_RATE
        )
        # File resampler: each AudioRawFrame / media chunk is a complete buffer
        # (Pipecat docs — use stream resampler only for open-ended streams).
        self._decode_resampler = create_file_resampler()
        self._encode_resampler = create_file_resampler()
        self._mulaw_out_buffer = bytearray()
        self._outbound_media_index = 0
        self._debug_encode_logged = False

    def _debug_log(self, hypothesis_id: str, location: str, message: str, data: dict) -> None:
        # region agent log
        try:
            payload = {
                "sessionId": "77bfe8",
                "hypothesisId": hypothesis_id,
                "location": location,
                "message": message,
                "data": data,
                "timestamp": int(time.time() * 1000),
            }
            with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, default=str) + "\n")
        except OSError:
            pass
        # endregion

    def _stream_sid_ready(self) -> bool:
        sid = (self._stream_sid or "").strip()
        return bool(sid) and sid.lower() != "unknown"

    @property
    def wire_sample_rate(self) -> int:
        return WIRE_SAMPLE_RATE

    async def setup(self, frame: StartFrame):
        rate = self._params.pipeline_sample_rate or frame.audio_in_sample_rate
        if rate and int(rate) > 0:
            self._pipeline_rate = int(rate)
        logger.info(
            "Go2Market serializer build={} wire={}Hz pipeline_pcm={}Hz "
            "preferred_mulaw_chunk={} stream_sid={}",
            GO2MARKET_SERIALIZER_BUILD,
            WIRE_SAMPLE_RATE,
            self._pipeline_rate,
            MULAW_PREFERRED_SEND_BYTES,
            self._stream_sid if self._stream_sid_ready() else "pending",
        )

    async def _send_ws(self, payload: str) -> None:
        """Send a media event that ``serialize`` cannot return (one payload per call)."""
        ws = self._websocket
        if ws is None:
            logger.warning("Go2Market media not sent; websocket is not attached")
            return
        await ws.send_text(payload)

    def update_stream_sid(self, stream_sid: str) -> None:
        value = (stream_sid or "").strip()
        if value and value.lower() != "unknown":
            self._stream_sid = value

    def _take_outbound_mulaw(self, *, force: bool = False) -> Optional[bytes]:
        """Take one wire chunk: 160 bytes or a multiple, at most 4000.

        Go2Market plays payloads that are not 160-byte aligned as noise, and
        rejects nothing above 4000 bytes cleanly. Send everything encoded so
        far instead of holding all but the first 40 ms.
        """
        if force and self._mulaw_out_buffer:
            padded = pad_mulaw_to_frame(bytes(self._mulaw_out_buffer))
            self._mulaw_out_buffer.clear()
            self._mulaw_out_buffer.extend(padded)

        aligned = align_mulaw_buffer(len(self._mulaw_out_buffer))
        if aligned < MULAW_FRAME_BYTES:
            return None
        target = min(aligned, MULAW_MAX_SEND_BYTES)
        target = align_mulaw_buffer(target) or target
        chunk = bytes(self._mulaw_out_buffer[:target])
        del self._mulaw_out_buffer[:target]
        return chunk

    def _json_media_out(self, mulaw_chunk: bytes) -> str:
        self._outbound_media_index += 1
        message = {
            "event": "media",
            "streamSid": self._stream_sid,
            "media": {
                "payload": base64.b64encode(mulaw_chunk).decode("ascii"),
                "chunk": self._outbound_media_index,
            },
        }
        return json.dumps(message)

    def _json_clear_out(self) -> str:
        return json.dumps({"event": "clear", "streamSid": self._stream_sid})

    async def _flush_mulaw_out(self, *, force: bool) -> Optional[str]:
        """Emit every ready µ-law chunk. The transport can send only one return value."""
        if not self._stream_sid_ready():
            return None
        messages: list[str] = []
        while True:
            chunk = self._take_outbound_mulaw(force=force and not messages)
            if not chunk:
                break
            messages.append(self._json_media_out(chunk))
            force = False
        if not messages:
            return None
        for extra in messages[:-1]:
            await self._send_ws(extra)
        return messages[-1]

    async def serialize(self, frame: Frame) -> str | bytes | None:
        if isinstance(frame, InterruptionFrame):
            self._mulaw_out_buffer.clear()
            if not self._stream_sid_ready():
                return None
            return self._json_clear_out()

        if isinstance(frame, (EndFrame, CancelFrame)):
            return await self._flush_mulaw_out(force=True)

        if isinstance(frame, AudioRawFrame):
            if not self._stream_sid_ready():
                return None
            pcm_rate = int(frame.sample_rate or self._pipeline_rate)
            mulaw = await encode_wire_mulaw(
                frame.audio,
                pcm_rate=pcm_rate,
                resampler=self._encode_resampler,
            )
            if not mulaw:
                return None
            if not self._debug_encode_logged:
                self._debug_encode_logged = True
                self._debug_log(
                    "H3-encode",
                    "serializers.py:serialize",
                    "first TTS frame encoded to wire mulaw",
                    {
                        "pcm_bytes": len(frame.audio),
                        "pcm_rate": pcm_rate,
                        "mulaw_bytes": len(mulaw),
                        "stream_sid_ready": self._stream_sid_ready(),
                        "preferred_chunk": MULAW_PREFERRED_SEND_BYTES,
                    },
                )
            self._mulaw_out_buffer.extend(mulaw)
            out = await self._flush_mulaw_out(force=False)
            if out and isinstance(out, str):
                try:
                    parsed = json.loads(out)
                    media = parsed.get("media") or {}
                    payload_len = len(base64.b64decode(str(media.get("payload") or "")))
                except Exception:
                    payload_len = -1
                if payload_len > 0 and self._outbound_media_index == 1:
                    self._debug_log(
                        "H4-outbound-json",
                        "serializers.py:serialize",
                        "first outbound media frame",
                        {
                            "streamSid": parsed.get("streamSid"),
                            "chunk": media.get("chunk"),
                            "mulaw_payload_bytes": payload_len,
                            "media_keys": sorted(media.keys()),
                        },
                    )
            return out

        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        try:
            message = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None
        if not isinstance(message, dict):
            return None

        event = str(message.get("event") or "").strip().lower()

        if event == "start":
            sid = resolve_stream_sid(message)
            if sid:
                self.update_stream_sid(sid)
            return None

        if event in ("connected", "mark"):
            return None

        if event == "stop":
            reason = (message.get("stop") or {}).get("reason", "")
            logger.info("Go2Market stream stop (reason={})", reason)
            return EndFrame()

        if event == "clear":
            return InterruptionFrame()

        if event == "dtmf":
            digit = (message.get("dtmf") or {}).get("digit")
            if not digit:
                return None
            try:
                return InputDTMFFrame(KeypadEntry(str(digit)))
            except ValueError:
                return None

        if event != "media":
            return None

        sid = message.get("streamSid")
        if sid:
            self.update_stream_sid(str(sid))

        media = message.get("media")
        if not isinstance(media, dict):
            return None

        payload_b64 = media.get("payload")
        if not payload_b64:
            return None

        try:
            mulaw = base64.b64decode(str(payload_b64), validate=True)
        except Exception:
            return None
        if not mulaw:
            return None

        pcm = await decode_wire_mulaw(
            mulaw,
            pipeline_rate=self._pipeline_rate,
            resampler=self._decode_resampler,
        )
        if not pcm:
            return None

        return InputAudioRawFrame(
            audio=pcm,
            num_channels=1,
            sample_rate=self._pipeline_rate,
        )
