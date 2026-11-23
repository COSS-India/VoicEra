"""Named POST /v1/lid/transcribe relays multipart audio to the LID slot."""
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI, File, UploadFile
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "gateway"))

from app.config import Settings, Upstream  # noqa: E402
from app.main import create_app  # noqa: E402
from conftest import free_port, serve  # noqa: E402


@pytest.fixture(scope="module")
def lid_upstream():
    hits: list[str] = []
    app = FastAPI()

    @app.get("/health")
    def health():
        hits.append("/health")
        return {"ok": True, "mode": "lid_transcribe"}

    @app.post("/transcribe")
    async def transcribe(audio: UploadFile = File(...)):
        hits.append("/transcribe")
        data = await audio.read()
        return {
            "detected_language": "kannada",
            "language_code": "kn",
            "confidence": 0.91,
            "duration_sec": 1.2,
            "transcript": "namaskara",
            "bytes": len(data),
        }

    port = free_port()
    serve(app, port)
    return {"url": f"http://127.0.0.1:{port}", "hits": hits}


def _client(lid_url: str) -> TestClient:
    settings = Settings(
        Upstream("stt", "", ""),
        Upstream("tts", "", ""),
        Upstream("llm", "", ""),
        Upstream("lid", lid_url, "nemotron-lid"),
    )
    return TestClient(create_app(settings))


def test_lid_health_passthrough(lid_upstream):
    with _client(lid_upstream["url"]) as c:
        r = c.get("/lid/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert "/health" in lid_upstream["hits"]


def test_lid_transcribe_named_route(lid_upstream):
    lid_upstream["hits"].clear()
    wav = b"RIFF" + b"\x00" * 40  # minimal payload; upstream only counts bytes
    with _client(lid_upstream["url"]) as c:
        r = c.post(
            "/v1/lid/transcribe",
            files={"audio": ("utterance.wav", wav, "audio/wav")},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["language_code"] == "kn"
    assert body["confidence"] == 0.91
    assert body["transcript"] == "namaskara"
    assert "/transcribe" in lid_upstream["hits"]


def test_lid_transcribe_503_when_slot_empty():
    settings = Settings(
        Upstream("stt", "", ""),
        Upstream("tts", "", ""),
        Upstream("llm", "", ""),
        # default lid Upstream is empty/disabled
    )
    with TestClient(create_app(settings)) as c:
        r = c.post(
            "/v1/lid/transcribe",
            files={"audio": ("u.wav", b"x", "audio/wav")},
        )
    assert r.status_code == 503
