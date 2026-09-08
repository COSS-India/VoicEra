"""OpenAI Realtime transcription WebSocket for indic-conformer.

Speaks the protocol expected by Pipecat's OpenAIRealtimeSTTService: session
events, input_audio_buffer.* client events, and word-by-word transcription
deltas via periodic buffer re-transcription through the shared batch worker.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import queue
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

OPENAI_INPUT_RATE = 24000
TARGET_SAMPLE_RATE = 16000
REALTIME_INTERIM_MS = int(os.environ.get("REALTIME_INTERIM_MS", "600"))
REALTIME_MAX_SESSIONS = int(os.environ.get("REALTIME_MAX_SESSIONS", "16"))

_active_lock = threading.Lock()
_active_sessions = 0


def active_session_count() -> int:
    with _active_lock:
        return _active_sessions


def _inc_sessions() -> bool:
    """Return False if at capacity."""
    global _active_sessions
    with _active_lock:
        if _active_sessions >= REALTIME_MAX_SESSIONS:
            return False
        _active_sessions += 1
        return True


def _dec_sessions() -> None:
    global _active_sessions
    with _active_lock:
        _active_sessions = max(0, _active_sessions - 1)


def resample_24k_to_16k(pcm_int16: np.ndarray) -> np.ndarray:
    """Convert int16 mono 24 kHz PCM to float32 mono 16 kHz."""
    if pcm_int16.size == 0:
        return np.array([], dtype=np.float32)
    x = pcm_int16.astype(np.float32) / 32768.0
    n_out = int(len(x) * TARGET_SAMPLE_RATE / OPENAI_INPUT_RATE)
    if n_out == 0:
        return np.array([], dtype=np.float32)
    indices = np.linspace(0, len(x) - 1, n_out)
    return np.interp(indices, np.arange(len(x)), x).astype(np.float32)


# The delta rule lives in realtime_protocol.py, vendored identically into every
# STT model folder so that switching model cannot change what a caller receives.
# Re-exported here because this module's own tests and callers import them.
from realtime_protocol import (  # noqa: E402
    DeltaEmitter,
    normalize_ws,
    word_prefix_extends,
)

__all__ = ["DeltaEmitter", "normalize_ws", "word_prefix_extends"]


def transcript_extends(last_emitted: str, full_text: str) -> bool:
    """True when full_text keeps everything already emitted (maybe grows at the end)."""
    last = normalize_ws(last_emitted)
    full = normalize_ws(full_text)
    if not last:
        return True
    return full.startswith(last)


def suffix_since(last_emitted: str, full_text: str) -> str:
    """New transcript text not yet emitted; full snapshot when the model revises."""
    last = normalize_ws(last_emitted)
    full = normalize_ws(full_text)
    if not full:
        return ""
    if not last:
        return full
    if full.startswith(last):
        return full[len(last) :].lstrip()
    return full





def new_words_since(last_emitted: str, full_text: str) -> list[str]:
    """Words in full_text not yet covered by last_emitted.

    Compare token-by-token so spacing or trailing punctuation drift on interim
    re-transcriptions does not re-emit the whole utterance."""
    full_words = full_text.split()
    if not full_words:
        return []
    last_words = last_emitted.split()
    if not last_words:
        return full_words
    common = 0
    for emitted, current in zip(last_words, full_words):
        if emitted == current:
            common += 1
        else:
            break
    return full_words[common:]


def _event_id() -> str:
    return f"evt_{uuid.uuid4().hex}"


@dataclass
class RealtimeDeps:
    """Callbacks into server.py queues and routing."""

    min_samples: int
    target_sample_rate: int
    bhili_enabled: bool
    bhili_loaded: bool
    is_bhili_language: Callable[[str], bool]
    request_queue_for: Callable[[str], queue.Queue]
    enqueue: Callable[[queue.Queue, np.ndarray, str], queue.Queue]
    queue_full_error: type[Exception]


@dataclass
class RealtimeSession:
    """Per-WebSocket transcription state."""

    language: str = "hi"
    model: str = "indic-conformer"
    session_ready: bool = False
    audio_buffer: np.ndarray = field(default_factory=lambda: np.array([], dtype=np.float32))
    #: The delta rule itself, vendored in realtime_protocol.py and shared with
    #: every other STT model. It owns item_id, content_index and the trailing
    #: word it is holding back -- this class used to keep its own copies and its
    #: own emit logic, which is how the two models in this slot ended up
    #: speaking measurably different protocols.
    deltas: DeltaEmitter = field(default_factory=DeltaEmitter)
    in_flight: bool = False
    #: Serialises inference for this session. `in_flight` alone let a commit
    #: that arrived while an interim was running return without transcribing,
    #: which ended the turn with no `completed` and no `committed` event.
    inference_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    interim_task: asyncio.Task | None = None
    last_interim_at: float = 0.0
    closed: bool = False

    def reset_segment(self) -> None:
        self.audio_buffer = np.array([], dtype=np.float32)
        self.deltas.reset()


class RealtimeProtocol:
    def __init__(self, ws: WebSocket, deps: RealtimeDeps) -> None:
        self._ws = ws
        self._deps = deps
        self._session = RealtimeSession()

    async def send_json(self, payload: dict) -> None:
        if self._session.closed:
            return
        await self._ws.send_text(json.dumps(payload))

    async def send_error(self, message: str, code: str = "server_error") -> None:
        await self.send_json({"type": "error", "error": {"message": message, "code": code}})

    async def send_session_created(self) -> None:
        await self.send_json(
            {
                "type": "session.created",
                "event_id": _event_id(),
                "session": {
                    "type": "realtime",
                    "object": "realtime.session",
                    "id": uuid.uuid4().hex,
                    "model": self._session.model,
                },
            }
        )

    async def send_session_updated(self) -> None:
        self._session.session_ready = True
        await self.send_json(
            {
                "type": "session.updated",
                "event_id": _event_id(),
                "session": {
                    "type": "transcription",
                    "audio": {
                        "input": {
                            "format": {"type": "audio/pcm", "rate": OPENAI_INPUT_RATE},
                            "transcription": {
                                "model": self._session.model,
                                "language": self._session.language,
                            },
                        },
                    },
                },
            }
        )

    async def send_completed(self, transcript: str) -> None:
        await self._session.deltas.completed(transcript, self.send_json)

    async def send_committed(self) -> None:
        await self.send_json(
            {
                "type": "input_audio_buffer.committed",
                "event_id": _event_id(),
                "item_id": self._session.deltas.item_id,
            }
        )

    async def send_cleared(self) -> None:
        await self.send_json(
            {
                "type": "input_audio_buffer.cleared",
                "event_id": _event_id(),
            }
        )

    def _parse_language(self, evt: dict) -> str | None:
        try:
            session = evt.get("session") or {}
            audio = session.get("audio") or {}
            inp = audio.get("input") or {}
            transcription = inp.get("transcription") or {}
            lang = transcription.get("language")
            if lang:
                return str(lang).split("-")[0].lower()
            model = transcription.get("model")
            if model:
                self._session.model = str(model)
        except (AttributeError, TypeError):
            pass
        return None

    async def handle_session_update(self, evt: dict) -> None:
        lang = self._parse_language(evt)
        if lang:
            self._session.language = lang
        await self.send_session_updated()

    async def _transcribe(self, audio_np: np.ndarray) -> str:
        lang = self._session.language
        if self._deps.is_bhili_language(lang):
            if not self._deps.bhili_enabled or not self._deps.bhili_loaded:
                raise RuntimeError("Bhili model is disabled")
        req_q = self._deps.request_queue_for(lang)

        try:
            response_q = self._deps.enqueue(req_q, audio_np.copy(), lang)
        except self._deps.queue_full_error as exc:
            raise RuntimeError("STT queue is full") from exc

        result = await asyncio.to_thread(response_q.get)
        if isinstance(result, BaseException):
            # The batch worker failed this request. Raising here reaches
            # _run_inference's RuntimeError path, which reports the error
            # AND ends the turn -- silence would hang the caller.
            raise RuntimeError(f"transcription failed: {result}") from result
        return result

    async def _emit_transcript_update(self, full_text: str) -> None:
        """Hand the snapshot to the shared delta rule and let it decide.

        This method used to hold its own copy of that rule, and the copy drifted
        the moment the rule changed: it still withdrew a revised word by
        advancing `content_index`, while indic-transcribe had moved to
        holding
        the trailing word until it settles. Two models in one slot, the same
        client, different transcripts. See realtime_protocol.py for why the
        append-only reading is the correct one.
        """
        await self._session.deltas.update(full_text, self.send_json)

    async def _run_inference(self, *, final: bool) -> None:
        if self._session.closed:
            return
        # An interim is best-effort: if one is already running, skip rather than
        # queue a second. A final is NOT best-effort. Returning here is what
        # silently dropped the end of a turn: handle_commit cancels the interim
        # first, but task.cancel() only *schedules* the CancelledError, so
        # in_flight is still True when we arrive. The lock below makes a final
        # wait for the in-flight interim instead of giving up on the turn.
        if self._session.in_flight and not final:
            return

        async with self._session.inference_lock:
            if self._session.closed:
                return
            if len(self._session.audio_buffer) < self._deps.min_samples:
                if final:
                    await self.send_completed("")
                    await self.send_committed()
                    self._session.reset_segment()
                return

            self._session.in_flight = True
            snapshot = self._session.audio_buffer.copy()
            try:
                text = await self._transcribe(snapshot)
            except RuntimeError as exc:
                await self.send_error(
                    str(exc),
                    code="queue_full" if "full" in str(exc).lower() else "transcription_error",
                )
                # A failed final still has to end the turn. Reporting the error and
                # returning leaves the caller waiting on a `completed` that never
                # comes, and leaves the segment un-reset, so the next utterance
                # concatenates onto this one and transcripts grow and repeat.
                if final:
                    await self.send_completed("")
                    await self.send_committed()
                    self._session.reset_segment()
                return
            finally:
                self._session.in_flight = False
                self._session.last_interim_at = time.monotonic()

            if self._session.closed:
                return

            await self._emit_transcript_update(text)

            if final:
                transcript = text.strip()
                await self.send_completed(transcript)
                await self.send_committed()
                self._session.reset_segment()

    def _cancel_interim(self) -> None:
        task = self._session.interim_task
        if task is not None and not task.done():
            task.cancel()
        self._session.interim_task = None

    def _schedule_interim(self) -> None:
        if self._session.closed or self._session.in_flight:
            return
        if len(self._session.audio_buffer) < self._deps.min_samples:
            return

        elapsed_ms = (time.monotonic() - self._session.last_interim_at) * 1000
        delay = max(0.0, (REALTIME_INTERIM_MS - elapsed_ms) / 1000)

        self._cancel_interim()

        async def _fire() -> None:
            try:
                await asyncio.sleep(delay)
                if not self._session.closed and not self._session.in_flight:
                    await self._run_inference(final=False)
            except asyncio.CancelledError:
                pass

        self._session.interim_task = asyncio.get_running_loop().create_task(_fire())

    async def handle_append(self, evt: dict) -> None:
        if not self._session.session_ready:
            return
        payload = evt.get("audio") or ""
        if not payload:
            return
        raw = base64.b64decode(payload)
        pcm = np.frombuffer(raw, dtype=np.int16)
        chunk = resample_24k_to_16k(pcm)
        if chunk.size:
            self._session.audio_buffer = np.concatenate([self._session.audio_buffer, chunk])
        self._schedule_interim()

    async def handle_commit(self) -> None:
        if not self._session.session_ready:
            return
        # Only cancel an interim that has not started inference yet. Cancelling
        # one mid-transcribe does NOT withdraw the request it already put on the
        # batch queue: that orphan still occupies a slot in the next batch and is
        # decoded for a caller that has gone away. The lock in _run_inference
        # already makes this final wait its turn, so letting a started interim
        # finish costs nothing and saves a redundant decode.
        if not self._session.in_flight:
            self._cancel_interim()
        await self._run_inference(final=True)

    async def handle_clear(self) -> None:
        self._cancel_interim()
        self._session.reset_segment()
        await self.send_cleared()

    async def handle_message(self, raw: str) -> None:
        try:
            evt = json.loads(raw)
        except json.JSONDecodeError:
            await self.send_error("Invalid JSON")
            return

        evt_type = evt.get("type", "")
        if evt_type == "session.update":
            await self.handle_session_update(evt)
        elif evt_type == "input_audio_buffer.append":
            await self.handle_append(evt)
        elif evt_type == "input_audio_buffer.commit":
            await self.handle_commit()
        elif evt_type == "input_audio_buffer.clear":
            await self.handle_clear()
        else:
            # Ignore unknown client events; OpenAI clients may send others.
            pass

    async def run(self) -> None:
        await self.send_session_created()
        try:
            while True:
                message = await self._ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                text = message.get("text")
                if text is not None:
                    await self.handle_message(text)
        finally:
            self._session.closed = True
            self._cancel_interim()


async def handle_realtime_ws(ws: WebSocket, deps: RealtimeDeps) -> None:
    """Entry point registered on FastAPI."""
    intent = ws.query_params.get("intent", "")
    if intent and intent != "transcription":
        await ws.accept()
        proto = RealtimeProtocol(ws, deps)
        await proto.send_error(f"Unsupported intent: {intent}", code="bad_request")
        await ws.close(code=1008)
        return

    if not _inc_sessions():
        await ws.accept()
        proto = RealtimeProtocol(ws, deps)
        await proto.send_error(
            f"At capacity: {REALTIME_MAX_SESSIONS} concurrent realtime sessions",
            code="at_capacity",
        )
        await ws.close(code=1013, reason="at capacity")
        return

    await ws.accept()
    proto = RealtimeProtocol(ws, deps)
    try:
        await proto.run()
    except WebSocketDisconnect:
        pass
    finally:
        proto._session.closed = True
        proto._cancel_interim()
        _dec_sessions()
