"""stt/hima-asr: the slot contract, with the Transformers model stubbed.

The model itself is never loaded -- load_model and warmup are replaced before
the app starts -- so this runs anywhere. What it pins is everything we wrote
around the model: /health gating, language handling, the 30 s split, batching
by language, and that the Realtime route speaks the same protocol as
indic-conformer's.
"""

from __future__ import annotations

import asyncio
import base64
import importlib
import io
import json
import sys
import wave
from pathlib import Path

import numpy as np
import pytest
import websockets
from conftest import free_port, serve

ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / "stt" / "hima-asr"
CONFORMER_DIR = ROOT / "stt" / "indic-conformer"


class HimaStub:
    """Stands in for HimaASRForConditionalGeneration.transcribe.

    Returns one word per 0.25 s of audio, tagged with the language it was asked
    for, and records every call so tests can see how the server batched.
    """

    def __init__(self):
        self.calls: list[dict] = []
        self.fail_language: str | None = None

    def transcribe(self, audio, language=None, style="native", batch_size=16):
        self.calls.append(
            {
                "n": len(audio),
                "language": language,
                "style": style,
                "lengths": [len(a) for a in audio],
            }
        )
        if language is not None and language == self.fail_language:
            raise RuntimeError("boom")
        tag = language or "auto"
        return [" ".join(f"{tag}{i}" for i in range(max(1, len(a) // 4000))) for a in audio]


@pytest.fixture(scope="module")
def hima():
    import os

    os.environ["REALTIME_INTERIM_MS"] = "50"
    os.environ["REALTIME_MAX_SESSIONS"] = "4"
    os.environ["HIMA_BATCH_WINDOW_MS"] = "30"

    # realtime_ws / realtime_protocol exist in several model folders under the
    # same module names; make sure this module gets hima-asr's copies.
    sys.path.insert(0, str(MODEL_DIR))
    for mod in ("server", "realtime_ws", "realtime_protocol"):
        sys.modules.pop(mod, None)
    server = importlib.import_module("server")
    stub = HimaStub()
    server.load_model = lambda: stub
    server.warmup = lambda _m: None

    port = free_port()
    serve(server.app, port)
    yield server, stub, port

    sys.path.remove(str(MODEL_DIR))
    for mod in ("server", "realtime_ws", "realtime_protocol"):
        sys.modules.pop(mod, None)


def _wav(seconds: float, rate: int = 16000, channels: int = 1) -> bytes:
    n = int(seconds * rate)
    pcm = (np.sin(np.arange(n) / 10) * 8000).astype(np.int16)
    if channels == 2:
        pcm = np.repeat(pcm, 2)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def _post(port: int, data: bytes, language: str | None):
    import httpx

    fields = {"model": "hima-asr"}
    if language is not None:
        fields["language"] = language
    return httpx.post(
        f"http://127.0.0.1:{port}/v1/audio/transcriptions",
        files={"file": ("a.wav", data, "audio/wav")},
        data=fields,
        timeout=10,
    )


# ---- folder hygiene --------------------------------------------------------


def test_realtime_protocol_is_the_shared_copy():
    """realtime_protocol.py is vendored identically into every Realtime STT
    folder, so that switching model cannot change what a caller receives."""
    assert (MODEL_DIR / "realtime_protocol.py").read_bytes() == (
        CONFORMER_DIR / "realtime_protocol.py"
    ).read_bytes()


def test_realtime_ws_differs_from_conformer_only_in_identity():
    ours = (MODEL_DIR / "realtime_ws.py").read_text().splitlines()
    theirs = (CONFORMER_DIR / "realtime_ws.py").read_text().splitlines()
    assert len(ours) == len(theirs)
    diff = [(a, b) for a, b in zip(ours, theirs, strict=True) if a != b]
    assert len(diff) == 2, diff
    assert all("hima-asr" in a for a, _ in diff)


def test_fetch_pins_a_commit_and_image_runs_offline():
    fetch = (MODEL_DIR / "fetch.sh").read_text()
    assert "--revision" in fetch
    assert "REVISION=${HIMA_REVISION:-" in fetch
    assert "@main" not in fetch
    dockerfile = (MODEL_DIR / "Dockerfile").read_text()
    assert "HF_HUB_OFFLINE=1" in dockerfile
    assert "--from=nemo" not in dockerfile


# ---- pure helpers ----------------------------------------------------------


def test_normalize_language(hima):
    server, _, _ = hima
    assert server.normalize_language("hi") == "hi"
    assert server.normalize_language("HI-IN") == "hi"
    assert server.normalize_language("od") == "or"
    assert server.normalize_language("") == server.AUTO
    assert server.normalize_language(None) == server.AUTO
    assert server.normalize_language("auto") == server.AUTO
    with pytest.raises(server.UnsupportedLanguage):
        server.normalize_language("bhb")
    with pytest.raises(server.UnsupportedLanguage):
        server.normalize_language("ur")


def test_split_long_audio_keeps_every_sample(hima):
    server, _, _ = hima
    sr = 16000
    audio = np.random.default_rng(0).normal(size=sr * 75).astype(np.float32)
    # a quiet stretch just before the 30 s mark should attract the first cut
    audio[int(sr * 28.5) : int(sr * 28.7)] = 0.0
    pieces = server.split_long_audio(audio, 30 * sr)
    assert len(pieces) == 3
    assert all(len(p) <= 30 * sr for p in pieces)
    assert np.array_equal(np.concatenate(pieces), audio)
    assert int(sr * 28.5) <= len(pieces[0]) <= int(sr * 28.7)


def test_split_short_audio_is_untouched(hima):
    server, _, _ = hima
    audio = np.zeros(16000 * 5, dtype=np.float32)
    assert len(server.split_long_audio(audio, 30 * 16000)) == 1


def test_infer_groups_by_language_and_confines_failures(hima):
    server, stub, _ = hima
    stub.calls.clear()
    stub.fail_language = "ta"
    a = np.zeros(16000, dtype=np.float32)
    batch = [
        {"audio_np": a, "language_id": "hi"},
        {"audio_np": a, "language_id": "ta"},
        {"audio_np": a, "language_id": "hi"},
        {"audio_np": a, "language_id": server.AUTO},
    ]
    try:
        out = server.infer(batch)
    finally:
        stub.fail_language = None
    assert out[0].startswith("hi0") and out[2].startswith("hi0")
    assert isinstance(out[1], server.InferenceFailed)
    assert out[3].startswith("auto0")
    langs = sorted(str(c["language"]) for c in stub.calls)
    assert langs == ["None", "hi", "ta"]  # one call per language; auto -> None
    assert next(c for c in stub.calls if c["language"] == "hi")["n"] == 2


def test_concurrent_posts_after_idle_share_a_batch(hima):
    """The window opens when the first request arrives, not when the worker
    last looked -- so requests arriving together after a quiet spell batch."""
    import time
    from concurrent.futures import ThreadPoolExecutor

    _, stub, port = hima
    time.sleep(0.3)  # idle for longer than the 30 ms window
    stub.calls.clear()
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(lambda _: _post(port, _wav(1.0), "hi"), range(4)))
    assert all(r.status_code == 200 for r in results)
    assert max(c["n"] for c in stub.calls) > 1, [c["n"] for c in stub.calls]


def test_long_clip_is_split_and_rejoined(hima):
    server, stub, _ = hima
    stub.calls.clear()
    audio = np.ones(16000 * 65, dtype=np.float32)
    [text] = server.infer([{"audio_np": audio, "language_id": "hi"}])
    assert stub.calls[-1]["n"] == 3
    assert all(n <= 30 * 16000 for n in stub.calls[-1]["lengths"])
    assert len(text.split()) == sum(n // 4000 for n in stub.calls[-1]["lengths"])


# ---- HTTP ------------------------------------------------------------------


def test_health_reports_the_model(hima):
    import httpx

    _, _, port = hima
    for _ in range(50):
        r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=5)
        if r.status_code == 200:
            break
        import time

        time.sleep(0.05)
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "hima-asr"
    assert body["status"] == "healthy"


def test_health_is_503_until_loaded(hima):
    import httpx

    server, stub, port = hima
    server.model = None
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=5)
        assert r.status_code == 503
        assert r.json()["status"] == "loading"
    finally:
        server.model = stub


def test_languages_route(hima):
    import httpx

    _, _, port = hima
    body = httpx.get(f"http://127.0.0.1:{port}/v1/languages", timeout=5).json()
    codes = {lang["code"] for lang in body["languages"]}
    assert codes == {"as", "bn", "en", "gu", "hi", "kn", "ml", "mr", "or", "pa", "ta", "te"}


def test_post_wav(hima):
    _, _, port = hima
    r = _post(port, _wav(1.0), "ta")
    assert r.status_code == 200, r.text
    assert r.json()["text"].startswith("ta0")


def test_post_resamples_any_rate_and_downmixes(hima):
    _, stub, port = hima
    stub.calls.clear()
    r = _post(port, _wav(2.0, rate=48000, channels=2), "hi")
    assert r.status_code == 200, r.text
    assert stub.calls[-1]["lengths"] == [32000]


def test_post_auto_language(hima):
    _, _, port = hima
    r = _post(port, _wav(1.0), None)
    assert r.status_code == 200
    assert r.json()["text"].startswith("auto0")


def test_post_rejects_unsupported_language(hima):
    _, _, port = hima
    r = _post(port, _wav(1.0), "bhb")
    assert r.status_code == 400
    assert "bhb" in r.json()["detail"]


# ---- Realtime --------------------------------------------------------------


def _session_update(language: str) -> str:
    return json.dumps(
        {
            "type": "session.update",
            "session": {
                "type": "transcription",
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": 24000},
                        "transcription": {"model": "hima-asr", "language": language},
                        "turn_detection": None,
                    }
                },
            },
        }
    )


def _append(n_24k: int = 24000) -> str:
    pcm = np.full(n_24k, 1000, dtype=np.int16)
    return json.dumps(
        {"type": "input_audio_buffer.append", "audio": base64.b64encode(pcm.tobytes()).decode()}
    )


async def _until(ws, wanted: str, limit: int = 30) -> list[dict]:
    seen = []
    for _ in range(limit):
        msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=5))
        seen.append(msg)
        if msg["type"] == wanted:
            return seen
    raise AssertionError(f"never saw {wanted}: {[m['type'] for m in seen]}")


@pytest.mark.asyncio
async def test_realtime_partials_then_completed(hima):
    _, _, port = hima
    async with websockets.connect(f"ws://127.0.0.1:{port}/v1/realtime?intent=transcription") as ws:
        created = json.loads(await ws.recv())
        assert created["session"]["model"] == "hima-asr"
        await ws.send(_session_update("te"))
        await _until(ws, "session.updated")

        await ws.send(_append())
        deltas = await _until(ws, "conversation.item.input_audio_transcription.delta")
        assert deltas[-1]["delta"].strip()

        await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        events = await _until(ws, "input_audio_buffer.committed")
        done = next(
            e
            for e in events
            if e["type"] == "conversation.item.input_audio_transcription.completed"
        )
        assert done["transcript"].startswith("te0")


@pytest.mark.asyncio
async def test_realtime_odia_alias(hima):
    _, stub, port = hima
    stub.calls.clear()
    async with websockets.connect(f"ws://127.0.0.1:{port}/v1/realtime?intent=transcription") as ws:
        await ws.recv()
        await ws.send(_session_update("or"))
        await _until(ws, "session.updated")
        await ws.send(_append())
        await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        await _until(ws, "input_audio_buffer.committed")
    assert any(c["language"] == "or" for c in stub.calls)


@pytest.mark.asyncio
async def test_realtime_unsupported_language_errors_and_ends_turn(hima):
    _, _, port = hima
    async with websockets.connect(f"ws://127.0.0.1:{port}/v1/realtime?intent=transcription") as ws:
        await ws.recv()
        await ws.send(_session_update("ks"))
        await _until(ws, "session.updated")
        await ws.send(_append())
        await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        events = await _until(ws, "input_audio_buffer.committed")
        errors = [e for e in events if e["type"] == "error"]
        assert errors and "ks" in errors[0]["error"]["message"]


# ---- standalone test stack ---------------------------------------------------


def test_standalone_environment_matches_the_slot_overlay():
    """compose.standalone.yml must run the deployment the slot would run, or a
    measurement on the test stack says nothing about the slot."""
    import yaml

    overlay = yaml.safe_load((MODEL_DIR / "compose.extra.yml").read_text())
    standalone = yaml.safe_load((MODEL_DIR / "compose.standalone.yml").read_text())
    slot_env = overlay["services"]["stt"]["environment"]
    test_env = standalone["services"]["stt"]["environment"]
    for key, value in slot_env.items():
        assert test_env.get(key) == value, key


def test_standalone_stack_cannot_touch_another_stack():
    import yaml

    doc = yaml.safe_load((MODEL_DIR / "compose.standalone.yml").read_text())
    assert doc["name"] == "voicera-hima-test"
    for name, svc in doc["services"].items():
        assert svc["container_name"].startswith("voicera_hima_test_"), name
        if "build" in svc:
            assert svc["image"].startswith("voicera-hima-test/"), name
        # localhost only: the box's public model port belongs to prod's gateway
        assert all(p.startswith("127.0.0.1:") for p in svc.get("ports", [])), name
    # the model itself publishes nothing; only this stack's gateway does
    assert "ports" not in doc["services"]["stt"]


def test_standalone_demo_is_reachable_at_demo_stt():
    """The tunnel points at the gateway, and the gateway at hima -- so the page
    is at /demo/stt and its /stt/... calls resolve, as on the real stack."""
    import yaml

    doc = yaml.safe_load((MODEL_DIR / "compose.standalone.yml").read_text())
    services = doc["services"]
    gw = services["gateway"]["environment"]
    assert gw["STT_MODEL"] == "hima-asr"
    assert gw["STT_UPSTREAM"] == "http://stt:8001"
    tunnel = services["tunnel"]
    assert tunnel["profiles"] == ["tunnel"]
    assert tunnel["command"][-1] == "http://gateway:8000"


def test_standalone_caps_cpu_memory_logs_and_gpu_memory():
    """A test stack on a shared box gets ceilings on everything it could take."""
    import yaml

    doc = yaml.safe_load((MODEL_DIR / "compose.standalone.yml").read_text())
    for name, svc in doc["services"].items():
        assert svc.get("cpus"), name
        assert svc.get("mem_limit"), name
        assert svc["logging"]["options"]["max-size"], name
    assert "HIMA_MAX_GPU_MEMORY_GB" in doc["services"]["stt"]["environment"]


def test_fetch_never_installs_into_the_host_python():
    fetch = (MODEL_DIR / "fetch.sh").read_text()
    code = "\n".join(line for line in fetch.splitlines() if not line.lstrip().startswith("#"))
    assert "--break-system-packages" not in code
    assert "pip3 install" not in code
    # the only pip is inside the throwaway container, into a private --target
    assert "--target /tmp/hf" in code


def test_teardown_removes_only_this_stacks_images():
    teardown = (MODEL_DIR / "tools" / "teardown.sh").read_text()
    code = "\n".join(line for line in teardown.splitlines() if not line.lstrip().startswith("#"))
    assert "--rmi" not in code
    assert "-p voicera-hima-test" in code
    assert "cloudflared" not in code
