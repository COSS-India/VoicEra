"""OpenAI Realtime WebSocket for indic-conformer (Pipecat-compatible)."""
import asyncio
import base64
import importlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest
import websockets
from conftest import free_port, serve


async def recv(ws, timeout: float = 5.0):
    return await asyncio.wait_for(ws.recv(), timeout=timeout)

ROOT = Path(__file__).resolve().parent.parent
STT_DIR = ROOT / "stt" / "indic-conformer"
sys.path.insert(0, str(STT_DIR))

from realtime_ws import (
    new_words_since,
    resample_24k_to_16k,
    suffix_since,
    transcript_extends,
    word_prefix_extends,
)


def _session_update(language: str = "hi") -> str:
    return json.dumps(
        {
            "type": "session.update",
            "session": {
                "type": "transcription",
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": 24000},
                        "transcription": {"model": "indic-conformer", "language": language},
                        "turn_detection": None,
                    },
                },
            },
        }
    )


def _append_b64(n_samples_24k: int = 4800, value: int = 1000) -> str:
    pcm = np.full(n_samples_24k, value, dtype=np.int16)
    payload = base64.b64encode(pcm.tobytes()).decode("ascii")
    return json.dumps({"type": "input_audio_buffer.append", "audio": payload})


class _WordStub:
    """Returns more words as audio grows; records batch sizes."""

    batch_sizes: list[int] = []

    def transcribe(self, audio=None, batch_size=None, language_id=None):
        out = []
        self.batch_sizes.append(len(audio))
        for arr in audio:
            n_words = max(1, len(arr) // 4000)
            out.append(" ".join(f"word{i}" for i in range(n_words)))
        return [out]

    def to(self, *a, **k):
        return self

    def freeze(self):
        return self


@pytest.fixture(scope="module")
def stt_ws_url():
    """Start indic-conformer with NeMo stub and word-generating model."""
    dummy = STT_DIR / "_test_stub.nemo"
    dummy.write_bytes(b"stub")

    os.environ["INDIC_NEMO_PATH"] = str(dummy)
    os.environ["BHILI_ENABLE"] = "no"
    os.environ["REALTIME_INTERIM_MS"] = "50"
    os.environ["REALTIME_MAX_SESSIONS"] = "8"

    sys.path.insert(0, str(STT_DIR))
    for mod in ("server", "realtime_ws"):
        sys.modules.pop(mod, None)

    server = importlib.import_module("server")
    stub = _WordStub()
    stub.batch_sizes = []
    server.main_model = stub
    server.bhili_model = None

    port = free_port()
    serve(server.app, port)
    # startup_event loads via stub restore_from; replace for deterministic transcripts.
    server.main_model = stub
    server.bhili_model = None
    yield f"ws://127.0.0.1:{port}", server, stub
    dummy.unlink(missing_ok=True)


def test_new_words_since_extends_prefix():
    assert new_words_since("", "नमस्ते दुनिया") == ["नमस्ते", "दुनिया"]
    assert new_words_since("नमस्ते", "नमस्ते दुनिया") == ["दुनिया"]
    assert new_words_since("नमस्ते दुनिया", "नमस्ते दुनिया") == []


def test_new_words_since_identical_retranscription():
    text = "हलो मेरा नाम कौशिक है"
    assert new_words_since(text, text) == []
    # Extra whitespace must not re-emit the full phrase (string startswith would fail).
    assert new_words_since(text, "हलो  मेरा  नाम  कौशिक  है") == []


def test_word_prefix_extends():
    assert word_prefix_extends("", "hello world")
    assert word_prefix_extends("hello", "hello world")
    assert not word_prefix_extends("hello world", "hello")
    assert not word_prefix_extends("hello there", "hello world")


def test_transcript_extends_suffix_for_partial_words():
    assert transcript_extends("హలో నా పేరు కౌ", "హలో నా పేరు కౌశిక")
    assert suffix_since("హలో నా పేరు కౌ", "హలో నా పేరు కౌశిక") == "శిక"
    assert not transcript_extends("హలో నా పేరు తె", "హలో నా పేరు కౌ")
    assert suffix_since("", "హలో నా పేరు కౌ") == "హలో నా పేరు కౌ"


def test_resample_24k_to_16k_changes_length():
    pcm = np.arange(2400, dtype=np.int16)
    out = resample_24k_to_16k(pcm)
    assert out.dtype == np.float32
    assert out.size == 1600


@pytest.mark.asyncio
async def test_handshake(stt_ws_url):
    url, _, _ = stt_ws_url
    async with websockets.connect(f"{url}/v1/realtime?intent=transcription") as ws:
        created = json.loads(await recv(ws))
        assert created["type"] == "session.created"

        await ws.send(_session_update("hi"))
        updated = json.loads(await recv(ws))
        assert updated["type"] == "session.updated"


@pytest.mark.asyncio
async def test_append_emits_deltas_before_commit(stt_ws_url):
    url, _, _ = stt_ws_url
    async with websockets.connect(f"{url}/v1/realtime?intent=transcription") as ws:
        await recv(ws)
        await ws.send(_session_update())
        await recv(ws)

        await ws.send(_append_b64(9600))
        seen_delta = False
        for _ in range(20):
            msg = json.loads(await recv(ws, timeout=2.0))
            if msg["type"] == "conversation.item.input_audio_transcription.delta":
                seen_delta = True
                assert msg.get("delta", "").strip()
                break
            await asyncio.sleep(0.05)
        assert seen_delta, "expected interim delta before commit"


@pytest.mark.asyncio
async def test_commit_lifecycle(stt_ws_url):
    url, _, _ = stt_ws_url
    async with websockets.connect(f"{url}/v1/realtime?intent=transcription") as ws:
        await recv(ws)
        await ws.send(_session_update())
        await recv(ws)

        await ws.send(_append_b64(9600))
        await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

        types = []
        for _ in range(10):
            msg = json.loads(await recv(ws, timeout=3.0))
            types.append(msg["type"])
            if msg["type"] == "input_audio_buffer.committed":
                break

        assert "conversation.item.input_audio_transcription.completed" in types
        assert "input_audio_buffer.committed" in types


@pytest.mark.asyncio
async def test_word_granularity(stt_ws_url):
    url, server, stub = stt_ws_url

    class HindiStub:
        batch_sizes = stub.batch_sizes

        def transcribe(self, audio=None, batch_size=None, language_id=None):
            # One result per batch item. A stub that always returns a single
            # result silently hands "" to every request after the first
            # whenever two land in the same batch, which reads as the server
            # losing a transcript.
            self.batch_sizes.append(len(audio))
            return [["नमस्ते दुनिया" for _ in audio]]

        def to(self, *a, **k):
            return self

        def freeze(self):
            return self

    server.main_model = HindiStub()

    async with websockets.connect(f"{url}/v1/realtime?intent=transcription") as ws:
        await recv(ws)
        await ws.send(_session_update())
        await recv(ws)
        await ws.send(_append_b64(9600))
        await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

        deltas = []
        for _ in range(10):
            msg = json.loads(await recv(ws, timeout=3.0))
            if msg["type"] == "conversation.item.input_audio_transcription.delta":
                deltas.append(msg["delta"].strip())
            if msg["type"] == "input_audio_buffer.committed":
                break

    assert len(deltas) >= 2
    assert any("नमस्ते" in d for d in deltas)
    assert any("दुनिया" in d for d in deltas)


@pytest.mark.asyncio
async def test_two_concurrent_sessions(stt_ws_url):
    url, _, _ = stt_ws_url

    async def one_session(tag: int):
        async with websockets.connect(f"{url}/v1/realtime?intent=transcription") as ws:
            await recv(ws)
            await ws.send(_session_update())
            await recv(ws)
            await ws.send(_append_b64(9600, value=tag))
            await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
            for _ in range(10):
                msg = json.loads(await recv(ws, timeout=3.0))
                if msg["type"] == "input_audio_buffer.committed":
                    return tag

    results = await asyncio.gather(one_session(1), one_session(2))
    assert results == [1, 2]


@pytest.mark.asyncio
async def test_batch_coalescing(stt_ws_url):
    url, _, stub = stt_ws_url
    stub.batch_sizes.clear()

    async def commit_once():
        async with websockets.connect(f"{url}/v1/realtime?intent=transcription") as ws:
            await recv(ws)
            await ws.send(_session_update())
            await recv(ws)
            await ws.send(_append_b64(9600))
            await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
            for _ in range(10):
                msg = json.loads(await recv(ws, timeout=5.0))
                if msg["type"] == "input_audio_buffer.committed":
                    return

    await asyncio.gather(commit_once(), commit_once())

    assert stub.batch_sizes, "expected at least one transcribe call"
    assert max(stub.batch_sizes) >= 2, f"expected batched infer, got sizes {stub.batch_sizes}"


def build_realtime_gateway(*, stt_url: str) -> str:
    from app.config import Settings, Upstream
    from app.main import create_app

    gw_port = free_port()
    settings = Settings(
        stt=Upstream("stt", stt_url.replace("ws://", "http://"), "indic-conformer"),
        tts=Upstream("tts", "", ""),
        llm=Upstream("llm", "", ""),
    )
    serve(create_app(settings), gw_port)
    return f"ws://127.0.0.1:{gw_port}"


@pytest.mark.asyncio
async def test_gateway_realtime_relay(stt_ws_url):
    upstream_http = stt_ws_url[0].replace("ws://", "http://", 1)
    gw = build_realtime_gateway(stt_url=upstream_http)

    headers = {"Authorization": "Bearer test-key"}
    async with websockets.connect(
        f"{gw}/v1/realtime?intent=transcription", additional_headers=headers
    ) as ws:
        created = json.loads(await recv(ws))
        assert created["type"] == "session.created"

        await ws.send(_session_update())
        updated = json.loads(await recv(ws))
        assert updated["type"] == "session.updated"

        await ws.send(_append_b64(9600))
        await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

        got_completed = False
        for _ in range(10):
            msg = json.loads(await recv(ws, timeout=3.0))
            if msg["type"] == "conversation.item.input_audio_transcription.completed":
                got_completed = True
            if msg["type"] == "input_audio_buffer.committed":
                break
        assert got_completed


# ---------------------------------------------- deltas across a revision

class _DeltaRecorder:
    """Stands in for the session, and reassembles deltas the way a client does.

    Plain concatenation, because that is what the protocol asks of a consumer
    and what a client we did not write will do. This used to reassemble by
    content_index, on the reading that advancing it withdrew what came before --
    which made the test agree with the implementation instead of with the spec,
    so the two agreed with each other and both were wrong. `content_index` is
    "the index of the content part in the item's content array", a position;
    the transcript is now append-only and nothing needs withdrawing.
    """

    def __init__(self, debounce_s: float = 0.20):
        from realtime_protocol import DeltaEmitter
        self.clock_t = 0.0
        emitter = DeltaEmitter(debounce_s=debounce_s, clock=lambda: self.clock_t)
        self._session = type("S", (), {"deltas": emitter})()
        self.items: dict[int, list[str]] = {}

    async def send_json(self, payload: dict) -> None:
        if payload["type"].endswith(".delta"):
            self.items.setdefault(payload["content_index"], []).append(payload["delta"])

    @property
    def transcript(self) -> str:
        return "".join(w for words in self.items.values() for w in words).strip()

    @property
    def content_items(self) -> int:
        return max(len(self.items), 1)


async def _replay(snapshots: list[str], step: float = 0.05) -> _DeltaRecorder:
    """Feed successive transcript snapshots through the real emitter.

    Ends with the turn ending, because that is when a client has the whole
    transcript: the trailing word is deliberately held until it settles, and a
    turn end settles it.
    """
    import inspect

    import realtime_ws
    cls = next(o for _, o in inspect.getmembers(realtime_ws, inspect.isclass)
               if hasattr(o, "_emit_transcript_update"))
    rec = _DeltaRecorder()
    for snap in snapshots:
        await cls._emit_transcript_update(rec, snap)
        rec.clock_t += step
    await rec._session.deltas.completed(snapshots[-1], rec.send_json)
    return rec


@pytest.mark.asyncio
@pytest.mark.parametrize(("snapshots", "expected"), [
    # The model resolves a partial token: "नम" turns out to be "नमस्ते".
    (["नम", "नमस्ते", "नमस्ते दुनिया"], "नमस्ते दुनिया"),
    (["hel", "hello", "hello world"], "hello world"),
    # A word replaced outright, not merely grown.
    (["hello there", "hello world"], "hello world"),
])
async def test_a_revised_word_does_not_arrive_in_pieces(snapshots, expected):
    """Two bugs, in the order they were made.

    Comparing snapshots character by character split words: "नम" -> "नमस्ते" is a
    character-prefix extension, so a character diff emits "स्ते" as its own
    delta and the consumer assembles "नम स्ते". Comparing whole words fixed that
    but still sent the wrong word first and withdrew it by advancing
    content_index -- which only works for a consumer that knows we mean that by
    it. Now the word is held until it cannot change, so the wrong version is
    never sent and a plain concatenation is simply right.
    """
    rec = await _replay(snapshots)
    assert rec.transcript == expected, "a word was split, or a revision reached the client"


@pytest.mark.asyncio
async def test_an_utterance_with_no_revisions_stays_in_one_item():
    """content_index is a position, not a version counter, so on a stream with
    nothing to correct it must never move."""
    rec = await _replay(["hello", "hello world", "hello world today"])
    assert rec.transcript == "hello world today"
    assert rec.content_items == 1, "content_index moved on a clean run"


@pytest.mark.asyncio
async def test_a_revision_costs_no_content_item_either():
    """The stronger claim, and the reason for the debounce: even across a
    revision the stream stays in one content part, because the revised word
    never went out in the first place."""
    rec = await _replay(["नम", "नमस्ते", "नमस्ते दुनिया"])
    assert rec.content_items == 1, \
        "a revision still reached the client and had to be withdrawn"


@pytest.mark.asyncio
async def test_every_delta_is_a_whole_word():
    """`send_delta(word)` is named for what it takes. A delta carrying a
    fragment gets a space appended to it, which is how a word gets broken."""
    rec = await _replay(["नम", "नमस्ते", "नमस्ते दुनिया"])
    for words in rec.items.values():
        for w in words:
            assert w.strip() and " " not in w.strip(), f"delta {w!r} is not one word"
