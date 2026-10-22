"""tts/higgs-tts-3: the adapter in front of the SGLang-Omni sidecar.

No GPU and no SGLang: the sidecar is a stub speaking the same wire as
sglang-omni 0.1.9's streaming /v1/audio/speech -- `audio/pcm` s16le, rate in
X-Sample-Rate, status line only once audio exists, outcome at
GET /v1/audio/speech/{id}. Both run on real sockets, because the two things
this adapter exists for -- streaming and cancellation -- are exactly what ASGI
test clients do not reproduce.

What is pinned, each a way this could break quietly:

* the slot contract: X-Audio-Format / X-Sample-Rate on every response, and pcm
  arriving byte-for-byte as the sidecar sent it
* a sample split across two HTTP chunks reaching an encoder whole
* `instructions` taking the fixed tag list only, and leading the text
* `speed` becoming a Higgs speed tag, never the sidecar's resampling `speed`
* a voice becoming its reference clip AND transcript
* a hang-up closing the sidecar request (which is what aborts generation there)
* OpenAI's error envelope, with a 400 before any GPU time is spent
"""
import asyncio
import base64
import importlib.util
import json
import struct
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
from conftest import free_port, serve
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

MODEL = Path(__file__).resolve().parent.parent / "tts" / "higgs-tts-3"
SIBLINGS = ("audio", "config", "tags", "upstream", "voices")


def _load():
    """Import the folder's modules without leaving generic names on sys.path.

    `config`, `audio` and `server` are names other model folders use too, so the
    folder is on sys.path only for the import and its siblings are put back the
    way they were -- the same discipline as test_rumik_vllm_backend.py.
    """
    saved = {n: sys.modules.pop(n) for n in (*SIBLINGS, "server") if n in sys.modules}
    sys.path.insert(0, str(MODEL))
    try:
        mods = {}
        for name in (*SIBLINGS, "server"):
            spec = importlib.util.spec_from_file_location(name, MODEL / f"{name}.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            mods[name] = mod
        return mods
    finally:
        sys.path.remove(str(MODEL))
        for n in (*SIBLINGS, "server"):
            sys.modules.pop(n, None)
        sys.modules.update(saved)


M = _load()
tags, server, config_mod = M["tags"], M["server"], M["config"]

RATE = 24000
#: Deliberately odd sizes: every boundary but the last splits a 16-bit sample.
CHUNKS = (b"\x01\x02\x03", b"\x04\x05", b"\x06\x07\x08\x09\x0a", b"\x0b")
PCM = b"".join(CHUNKS)


# --------------------------------------------------------------------- sidecar
class Sidecar:
    """Stand-in for SGLang-Omni serving Higgs. Records what it was asked."""

    def __init__(self):
        self.requests: list[dict] = []
        self.aborted = threading.Event()
        self.completed = 0
        self.slow = False
        self.finish_reason = "stop"
        self.app = self._build()

    def _build(self):
        app = FastAPI()

        @app.get("/health")
        async def health():
            return {"status": "healthy", "running": True}

        @app.get("/v1/audio/speech/{speech_id}")
        async def outcome(speech_id: str):
            return {"request_id": speech_id, "finish_reason": self.finish_reason}

        @app.post("/v1/audio/speech")
        async def speech(request: Request):
            body = await request.json()
            self.requests.append(body)
            if "REFUSE" in body["input"]:
                return JSONResponse(status_code=400, content={"error": {
                    "message": "reference audio unreadable", "type": "BadRequestError",
                    "param": "references", "code": 400}})

            async def gen():
                finished = False
                try:
                    for chunk in CHUNKS:
                        yield chunk
                        await asyncio.sleep(0.5 if self.slow else 0.01)
                    if self.slow:
                        for _ in range(200):
                            yield b"\x00\x00"
                            await asyncio.sleep(0.05)
                    finished = True
                    self.completed += 1
                finally:
                    if not finished:
                        self.aborted.set()

            return StreamingResponse(gen(), media_type="audio/pcm", headers={
                "X-Sample-Rate": str(RATE), "X-Channels": "1", "X-Bit-Depth": "16",
                "X-SGLang-Omni-Speech-Id": "speech-test"})

        return app


@pytest.fixture
def voices_dir(tmp_path):
    (tmp_path / "refs").mkdir()
    (tmp_path / "refs" / "aditi.wav").write_bytes(b"RIFF")
    (tmp_path / "manifest.json").write_text(json.dumps({"default": "Aditi", "voices": [
        {"name": "Aditi", "gender": "female", "language": "hi", "ref": "aditi.wav",
         "text": "यह एक संदर्भ वाक्य है।"},
        {"name": "Meera", "gender": "female", "language": "ta", "ref": "meera.wav", "text": ""},
    ]}), encoding="utf-8")
    return tmp_path


@pytest.fixture
def stack(voices_dir, monkeypatch):
    """A stub sidecar and the real adapter in front of it, both on sockets."""
    side = Sidecar()
    side_port = free_port()
    side_server = serve(side.app, side_port)
    monkeypatch.setenv("HIGGS_SIDECAR_URL", f"http://127.0.0.1:{side_port}")
    monkeypatch.setenv("HIGGS_VOICES_DIR", str(voices_dir))
    cfg = config_mod.Config.from_env()
    port = free_port()
    adapter_server = serve(server.create_app(cfg), port)
    yield side, f"http://127.0.0.1:{port}"
    adapter_server.should_exit = True
    side_server.should_exit = True


def post(base, **body):
    body.setdefault("input", "नमस्ते")
    body.setdefault("voice", "Aditi")
    return httpx.post(f"{base}/v1/audio/speech", json=body, timeout=10)


# ------------------------------------------------------------------- contract
def test_pcm_is_a_byte_for_byte_pass_through(stack):
    side, base = stack
    r = post(base, response_format="pcm")
    assert r.status_code == 200, r.text
    # The odd trailing byte is half a sample; whole samples only, in order.
    assert r.content == PCM[: len(PCM) - len(PCM) % 2]
    assert r.headers["x-audio-format"] == "pcm"
    assert r.headers["x-sample-rate"] == str(RATE)
    assert r.headers["content-type"].startswith("audio/pcm")


def test_the_sidecar_is_always_asked_for_streamed_pcm(stack):
    side, base = stack
    post(base, response_format="wav")
    sent = side.requests[-1]
    assert sent["stream"] is True and sent["response_format"] == "pcm"
    # The sidecar's own `speed` resamples (pitch shift); speed is a tag instead.
    assert sent["speed"] == 1.0
    assert sent["model"] == "higgs-tts-3"


def test_wav_is_buffered_with_a_true_length(stack):
    _side, base = stack
    r = post(base, response_format="wav")
    assert r.status_code == 200, r.text
    data_len = struct.unpack("<I", r.content[40:44])[0]
    assert data_len == len(r.content) - 44 == len(PCM) - len(PCM) % 2
    assert r.headers["x-audio-format"] == "wav"
    assert "x-generation-ms" in r.headers


def test_sse_carries_openai_events_and_a_done(stack):
    _side, base = stack
    r = post(base, response_format="pcm", stream_format="sse")
    assert r.status_code == 200, r.text
    events = [json.loads(line[6:]) for line in r.text.splitlines() if line.startswith("data: ")]
    deltas = [e for e in events if e["type"] == "speech.audio.delta"]
    assert b"".join(base64.b64decode(e["audio"]) for e in deltas) == PCM[:-1]
    assert events[-1]["type"] == "speech.audio.done"
    assert events[-1]["truncated"] is False


def test_hitting_the_token_cap_is_reported(stack):
    side, base = stack
    side.finish_reason = "length"
    r = post(base, response_format="wav")
    assert r.headers.get("x-truncated") == "true"


def test_flac_over_sse_is_refused_before_the_gpu_is_used(stack):
    side, base = stack
    r = post(base, response_format="flac", stream_format="sse")
    assert r.status_code == 400
    assert r.json()["error"]["param"] == "response_format"
    assert side.requests == []


# ---------------------------------------------------------------------- voice
def test_a_voice_is_its_clip_and_transcript(stack):
    side, base = stack
    post(base, voice="aditi")       # case-insensitive, like a person types it
    ref = side.requests[-1]["references"]
    assert ref == [{"audio_path": "/voices/refs/aditi.wav", "text": "यह एक संदर्भ वाक्य है।"}]


def test_an_unknown_voice_is_a_400_naming_the_roster(stack):
    side, base = stack
    r = post(base, voice="Zoya")
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["param"] == "voice" and "Aditi" in err["message"]
    assert side.requests == []


def test_a_voice_without_its_clip_says_how_to_get_it(stack):
    side, base = stack
    r = post(base, voice="Meera")
    assert r.status_code == 503
    assert "fetch_voices.py" in r.json()["error"]["message"]
    assert side.requests == []


def test_zero_shot_is_off_unless_asked_for(stack):
    side, base = stack
    r = post(base, voice="default")
    assert r.status_code == 400
    assert "HIGGS_ALLOW_ZERO_SHOT" in r.json()["error"]["message"]


# ----------------------------------------------------------------------- tags
def test_instructions_lead_the_text_in_a_fixed_order(stack):
    side, base = stack
    r = post(base, input="ठीक है", instructions="prosody:pitch_low, <|emotion:elation|> whispering")
    assert r.status_code == 200, r.text
    assert side.requests[-1]["input"] == (
        "<|emotion:elation|><|style:whispering|><|prosody:pitch_low|>ठीक है")


def test_free_text_instructions_are_refused(stack):
    side, base = stack
    r = post(base, instructions="happy and a bit fast")
    assert r.status_code == 400
    assert r.json()["error"]["param"] == "instructions"
    assert side.requests == []


def test_speed_becomes_the_nearest_speed_tag(stack):
    side, base = stack
    r = post(base, input="hello", speed=1.25)
    assert r.headers["x-speed-applied"] == "speed_fast"
    assert side.requests[-1]["input"].startswith("<|prosody:speed_fast|>")


def test_speed_that_contradicts_instructions_is_refused(stack):
    _side, base = stack
    r = post(base, speed=0.6, instructions="prosody:speed_fast")
    assert r.status_code == 400
    assert r.json()["error"]["param"] == "speed"


def test_unknown_tag_in_input_is_refused_not_spoken(stack):
    side, base = stack
    r = post(base, input="hello <|sfx:applause|>")
    assert r.status_code == 400
    assert r.json()["error"]["param"] == "input"
    ok = post(base, input="ha <|sfx:laughter|>Haha <|prosody:pause|> done")
    assert ok.status_code == 200


@pytest.mark.parametrize("speed,tag", [
    (0.25, "speed_very_slow"), (0.7, "speed_very_slow"), (0.8, "speed_slow"),
    (1.0, None), (1.05, None), (1.15, "speed_fast"), (1.35, "speed_very_fast"),
    (4.0, "speed_very_fast"),
])
def test_speed_rounding(speed, tag):
    assert tags.speed_tag(speed) == tag


def test_an_inline_tag_in_instructions_points_to_input():
    with pytest.raises(tags.TagError, match="inline tag"):
        tags.parse_instructions("sfx:laughter")


def test_two_emotions_are_a_contradiction():
    with pytest.raises(tags.TagError, match="two emotion"):
        tags.parse_instructions("emotion:anger, sadness")


def test_every_documented_value_is_accepted():
    for option in tags.instruction_options():
        assert tags.parse_instructions(option).slots


# ------------------------------------------------------------- errors, health
def test_a_sidecar_refusal_keeps_its_message(stack):
    _side, base = stack
    r = post(base, input="REFUSE this")
    assert r.status_code == 400
    assert "reference audio unreadable" in r.json()["error"]["message"]


def test_too_long_an_input_is_a_400_saying_so(stack):
    _side, base = stack
    r = post(base, input="क" * 401)
    assert r.status_code == 400 and "HIGGS_MAX_INPUT_CHARS" in r.json()["error"]["message"]


def test_validation_errors_use_the_openai_envelope(stack):
    _side, base = stack
    r = post(base, response_format="aiff")
    assert r.status_code == 400
    assert r.json()["error"]["param"] == "response_format"


def test_health_needs_the_sidecar_and_a_usable_voice(stack, voices_dir):
    _side, base = stack
    r = httpx.get(f"{base}/health")
    assert r.status_code == 200 and r.json()["voices"] == ["Aditi"]


def test_health_is_503_with_no_clips(voices_dir, monkeypatch):
    (voices_dir / "refs" / "aditi.wav").unlink()
    monkeypatch.setenv("HIGGS_SIDECAR_URL", "http://127.0.0.1:9")   # nothing listens
    monkeypatch.setenv("HIGGS_VOICES_DIR", str(voices_dir))
    port = free_port()
    srv = serve(server.create_app(config_mod.Config.from_env()), port)
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/health")
        assert r.status_code == 503
        assert r.json()["status"] == "loading"
        v = httpx.get(f"http://127.0.0.1:{port}/v1/voices").json()
        assert [d["available"] for d in v["data"]] == [False, False]
        assert "emotion:elation" in v["instructions"]
    finally:
        srv.should_exit = True


# --------------------------------------------------------------- cancellation
def test_a_hang_up_closes_the_sidecar_request(stack):
    """The point of streaming over HTTP: barge-in frees the GPU.

    The caller reads one chunk and leaves. The sidecar must see its own stream
    closed before it finished -- in SGLang-Omni that disconnect is what aborts
    the request in the engine.
    """
    side, base = stack
    side.slow = True
    with httpx.Client(timeout=10) as client, client.stream("POST", f"{base}/v1/audio/speech",
                       json={"input": "नमस्ते", "voice": "Aditi",
                             "response_format": "pcm"}) as r:
        assert r.status_code == 200
        next(r.iter_raw())
    deadline = time.time() + 5
    while time.time() < deadline and not side.aborted.is_set():
        time.sleep(0.05)
    assert side.aborted.is_set(), "the sidecar kept generating after the caller hung up"
    assert side.completed == 0
