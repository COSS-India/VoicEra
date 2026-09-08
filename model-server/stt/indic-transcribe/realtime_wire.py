"""Two wire formats over one streaming implementation.

`/v1/asr/ws` and `/v1/realtime` carry the same conversation: audio in, revised
transcripts out. They disagree only about envelopes -- what the handshake looks
like, how audio arrives, how a transcript update is spelled, and what "I have
finished speaking" is called.

Everything underneath is identical, and must stay that way. The turn machinery
in app.py is not incidental: sessions rotate mid-stream because a decoder's
state grows without bound against a hard 1024-position limit, and running past
it surfaces as a CUDA illegal memory access from an unrelated kernel rather than
a clean error. A second transport that reimplemented turns would reintroduce
that crash on exactly the long calls it would be used for.

So the transport is a parameter, not a copy. Adding a third would mean another
class here and nothing else.
"""

from __future__ import annotations

import base64
import json

import numpy as np
from realtime_protocol import DeltaEmitter, event_id

# OpenAI Realtime carries PCM16 at 24 kHz; this engine decodes at 16 kHz.
OPENAI_INPUT_RATE = 24000


def _resample_24k_to_16k(pcm_int16: np.ndarray) -> np.ndarray:
    """24 kHz int16 -> 16 kHz float32, by linear interpolation.

    Deliberately not a windowed resampler: this runs per audio chunk on the hot
    path of a live call, and the engine's own feature extractor is downstream of
    it. The artefacts a better filter would remove sit above the band this model
    attends to.
    """
    if pcm_int16.size == 0:
        return np.array([], dtype=np.float32)
    x = pcm_int16.astype(np.float32) / 32768.0
    n_out = int(len(x) * 16000 / OPENAI_INPUT_RATE)
    if n_out == 0:
        return np.array([], dtype=np.float32)
    idx = np.linspace(0, len(x) - 1, n_out)
    return np.interp(idx, np.arange(len(x)), x).astype(np.float32)


class NativeWire:
    """The protocol this model has always spoken. Unchanged, deliberately.

    Kept so the existing route keeps working byte for byte while the OpenAI one
    is proven. It should go once nothing depends on it -- two protocols in one
    slot means every future model author has to ask which to implement.
    """

    name = "native"

    def __init__(self, ws):
        self.ws = ws

    async def handshake(self, info: dict) -> None:
        await self.ws.send_json({"type": "ready", **info})

    def decode_audio(self, raw: bytes) -> np.ndarray:
        return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    def parse_text(self, text: str) -> tuple[str, dict]:
        try:
            cmd = json.loads(text)
        except json.JSONDecodeError:
            cmd = {"type": text.strip()}
        return cmd.get("type", ""), cmd

    async def transcript(self, *, turn: int, text: str, full_text: str,
                         transcript: str, is_turn_end: bool, extra: dict) -> None:
        await self.ws.send_json({
            "type": "turn_final" if is_turn_end else "partial",
            "turn": turn, "text": text, "full_text": full_text,
            "transcript": transcript, **extra,
        })

    async def closed(self, transcript: str) -> None:
        await self.ws.send_json({"type": "closed", "transcript": transcript})

    async def error(self, kind: str, message: str, **extra) -> None:
        await self.ws.send_json({"type": "error", "error": message,
                                 "reason": kind, **extra})


class OpenAIRealtimeWire:
    """OpenAI Realtime transcription, which Pipecat already has a client for.

    Choosing a published spec over one of our own is the point: the voice
    pipeline gets a transcriber it can talk to without us writing and
    maintaining a client for it.
    """

    name = "openai-realtime"

    def __init__(self, ws):
        self.ws = ws
        self.deltas = DeltaEmitter()
        self._session_id = f"sess_{event_id()[6:]}"

    async def _send(self, payload: dict) -> None:
        await self.ws.send_json(payload)

    async def handshake(self, info: dict) -> None:
        await self._send({
            "type": "session.created",
            "event_id": event_id(),
            "session": {
                "id": self._session_id,
                "object": "realtime.transcription_session",
                "audio": {"input": {
                    "format": {"type": "audio/pcm", "rate": OPENAI_INPUT_RATE},
                    "transcription": {"model": info.get("model", "indic-transcribe"),
                                      "language": info.get("language")},
                }},
            },
        })

    def decode_audio(self, raw: bytes) -> np.ndarray:
        """Binary frames are still accepted, and are 24 kHz here.

        The spec sends audio base64-encoded inside `input_audio_buffer.append`,
        which `parse_text` handles. Raw binary is tolerated because it costs
        nothing and saves a client a 33% encoding overhead on the hot path.
        """
        return _resample_24k_to_16k(np.frombuffer(raw, dtype=np.int16))

    def parse_text(self, text: str) -> tuple[str, dict]:
        """Translate a client event into the verbs the stream loop knows.

        Returns one of "", "audio", "stop", "commit" -- the same vocabulary the
        native wire produces, so the loop below never learns which protocol it
        is speaking.
        """
        try:
            evt = json.loads(text)
        except json.JSONDecodeError:
            return "", {}
        kind = evt.get("type", "")

        if kind == "input_audio_buffer.append":
            audio_b64 = evt.get("audio") or ""
            try:
                pcm = np.frombuffer(base64.b64decode(audio_b64), dtype=np.int16)
            except Exception:                                       # noqa: BLE001
                return "", {}
            return "audio", {"pcm": _resample_24k_to_16k(pcm)}

        if kind == "input_audio_buffer.commit":
            return "commit", evt
        if kind in ("input_audio_buffer.clear", "session.close"):
            return "stop", evt
        if kind in ("session.update", "transcription_session.update"):
            return "session.update", evt
        return "", evt

    @staticmethod
    def requested_language(evt: dict) -> str | None:
        """The language a `session.update` is asking for, or None.

        Two nestings are in circulation -- the current
        `session.audio.input.transcription` and the older
        `session.input_audio_transcription` -- and both appear in clients built
        against different revisions of the spec. Reading them here keeps app.py
        from learning either shape, which is the whole point of the wire split.
        """
        try:
            session = evt.get("session") or {}
            audio_in = ((session.get("audio") or {}).get("input") or {})
            tr = (audio_in.get("transcription")
                  or session.get("input_audio_transcription")
                  or {})
            lang = tr.get("language")
        except (AttributeError, TypeError):
            return None
        if not lang:
            return None
        # "ta-IN" -> "ta". Normalised exactly as indic-conformer normalises it:
        # both models fill the same slot, so a client that works against one and
        # is rejected by the other makes the slot a lie.
        return str(lang).split("-")[0].lower()

    async def session_updated(self, info: dict) -> None:
        await self._send({
            "type": "session.updated",
            "event_id": event_id(),
            "session": {"id": self._session_id,
                        "audio": {"input": {"transcription": {
                            "model": info.get("model", "indic-transcribe"),
                            "language": info.get("language")}}}},
        })

    async def transcript(self, *, turn: int, text: str, full_text: str,  # noqa: ARG002
                         transcript: str, is_turn_end: bool, extra: dict) -> None:  # noqa: ARG002
        """One rule, shared with every other STT model: whole words, and a
        revision withdraws rather than patches. See realtime_protocol.py.

        `turn`, `text`, `full_text` and `extra` are deliberately unused. They
        are the native protocol's per-turn diagnostics -- which turn produced
        this, its latency, its partial count -- and the OpenAI spec has nowhere
        to put them. They stay in the signature because the native wire needs
        them and both wires answer the same call.
        """
        await self.deltas.update(transcript, self._send)
        if is_turn_end:
            await self.deltas.completed(transcript, self._send)
            await self._send({
                "type": "input_audio_buffer.committed",
                "event_id": event_id(),
                "item_id": self.deltas.item_id,
            })
            # A turn ended, not the stream. The next turn is a new content item,
            # so the consumer does not append the next sentence onto this one.
            self.deltas.reset()

    async def closed(self, transcript: str) -> None:            # noqa: ARG002
        """Nothing on the wire. The socket closing is the end of the stream.

        There is no `session.closed` server event in the OpenAI Realtime spec,
        and this used to invent one. A spec client ignores an event type it does
        not know, so it was inert rather than harmful -- but it was one more
        thing a reader had to check the spec for and not find, and
        indic-conformer never sent it, so the same slot ended two streams two
        different ways. The last turn's `.completed` already carried the final
        transcript; `transcript` here would only repeat it.
        """
        return

    async def error(self, kind: str, message: str, **extra) -> None:
        await self._send({
            "type": "error",
            "event_id": event_id(),
            "error": {"type": kind, "message": message, **extra},
        })
