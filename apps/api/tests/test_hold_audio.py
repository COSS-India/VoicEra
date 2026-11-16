"""Hold-audio upload API and behaviour validation tests."""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.models.schemas import AgentConfigPayload
from app.routers import hold_audio
from app.services import hold_audio_service
from app.services.agent_config_validation import (
    AgentConfigValidationError,
    validate_agent_config,
)

_FIXTURES = Path(__file__).resolve().parent / "fixtures"
_MP3_PATH = _FIXTURES / "hold_test.mp3"


def _admin_user() -> dict[str, Any]:
    return {"email": "admin@example.com", "org_id": "org-1", "role": "admin"}


def _pcm_wav(*, sample_rate: int = 8000, frames: int = 160) -> bytes:
    pcm = b"\x00\x00" * frames
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _agent_config(**behaviour_overrides: Any) -> AgentConfigPayload:
    behaviour: dict[str, Any] = {
        "hold_mode": "text",
        "hold_messages": [],
        "hold_audio_clips": [],
        "hold_message_timeout_seconds": 0.6,
    }
    behaviour.update(behaviour_overrides)
    return AgentConfigPayload.model_validate(
        {
            "schema_version": 1,
            "prompts": {
                "system_prompt": "You are helpful.",
                "greeting_message": "Hello!",
            },
            "behaviour": behaviour,
            "language": {"primary": "en", "secondary": []},
            "models": {
                "en": {
                    "stt_config": {"provider": "openai", "model": "gpt-4o-transcribe"},
                    "tts_config": {
                        "provider": "openai",
                        "model": "gpt-4o-mini-tts",
                        "voice": "alloy",
                    },
                    "llm_config": {"provider": "openai", "model": "gpt-4o-mini"},
                }
            },
            "knowledge_base": {
                "enabled": False,
                "mode": "context",
                "document_ids": [],
                "top_k": 5,
            },
        }
    )


@pytest.fixture
def hold_audio_client() -> TestClient:
    app = FastAPI()
    app.include_router(hold_audio.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = _admin_user
    return TestClient(app)


def test_validate_upload_rejects_unsupported_type() -> None:
    with pytest.raises(hold_audio_service.HoldAudioError, match="WAV and MP3"):
        hold_audio_service.validate_upload("note.m4a", b"not-audio")


def test_validate_upload_rejects_bad_wav_header() -> None:
    with pytest.raises(hold_audio_service.HoldAudioError, match="WAV"):
        hold_audio_service.validate_upload("note.wav", b"RIFF....NOTWAVE")


def test_validate_upload_rejects_bad_mp3() -> None:
    with pytest.raises(hold_audio_service.HoldAudioError, match="MP3"):
        hold_audio_service.validate_upload("note.mp3", b"not-an-mp3")


def test_validate_upload_rejects_oversize(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.hold_audio_service.settings.HOLD_AUDIO_MAX_UPLOAD_BYTES",
        64,
    )
    data = _pcm_wav(frames=10_000)
    with pytest.raises(hold_audio_service.HoldAudioError, match="too large"):
        hold_audio_service.validate_upload("big.wav", data)


def test_validate_upload_accepts_pcm_wav() -> None:
    name, fmt = hold_audio_service.validate_upload("hold.wav", _pcm_wav())
    assert name == "hold.wav"
    assert fmt == "wav"


def test_validate_upload_accepts_mp3() -> None:
    data = _MP3_PATH.read_bytes()
    name, fmt = hold_audio_service.validate_upload("hold.mp3", data)
    assert name == "hold.mp3"
    assert fmt == "mp3"


def test_assert_org_storage_key_rejects_cross_tenant() -> None:
    with pytest.raises(hold_audio_service.HoldAudioError):
        hold_audio_service.assert_org_storage_key(
            "org-1",
            "hold-audio/org-2/clip/a.wav",
        )


def test_validate_behaviour_clips_ok() -> None:
    hold_audio_service.validate_behaviour_clips(
        "org-1",
        [
            {
                "clip_id": "c1",
                "storage_key": "hold-audio/org-1/c1/a.wav",
                "filename": "a.wav",
            }
        ],
    )


def test_validate_agent_config_rejects_foreign_hold_key() -> None:
    config = _agent_config(
        hold_mode="audio",
        hold_audio_clips=[
            {
                "clip_id": "c1",
                "storage_key": "hold-audio/other/c1/a.wav",
                "filename": "a.wav",
            }
        ],
    )
    with pytest.raises(AgentConfigValidationError, match="hold-audio/org-1/"):
        validate_agent_config(config, org_id="org-1")


def test_validate_agent_config_accepts_org_hold_key() -> None:
    config = _agent_config(
        hold_mode="audio",
        hold_audio_clips=[
            {
                "clip_id": "c1",
                "storage_key": "hold-audio/org-1/c1/a.wav",
                "filename": "a.wav",
            }
        ],
    )
    validated = validate_agent_config(config, org_id="org-1")
    assert validated.behaviour.hold_mode == "audio"
    assert validated.behaviour.hold_audio_clips[0].clip_id == "c1"


def test_upload_endpoint_stores_wav(hold_audio_client: TestClient) -> None:
    with patch(
        "app.services.hold_audio_service.upload_clip",
        return_value={
            "clip_id": "clip-1",
            "storage_key": "hold-audio/org-1/clip-1/hold.wav",
            "filename": "hold.wav",
        },
    ) as mock_upload:
        response = hold_audio_client.post(
            "/api/v1/hold-audio/upload",
            files={"file": ("hold.wav", _pcm_wav(), "audio/wav")},
        )
    assert response.status_code == 201
    body = response.json()
    assert body["clip_id"] == "clip-1"
    assert body["storage_key"].startswith("hold-audio/org-1/")
    mock_upload.assert_called_once()


def test_upload_endpoint_rejects_unsupported(hold_audio_client: TestClient) -> None:
    response = hold_audio_client.post(
        "/api/v1/hold-audio/upload",
        files={"file": ("note.m4a", b"abc", "audio/mp4")},
    )
    assert response.status_code == 400
    assert "WAV and MP3" in response.json()["detail"]


@patch("app.services.hold_audio_service.delete_clip")
def test_delete_endpoint(
    mock_delete: MagicMock,
    hold_audio_client: TestClient,
) -> None:
    response = hold_audio_client.delete(
        "/api/v1/hold-audio/clip-1",
        params={"storage_key": "hold-audio/org-1/clip-1/hold.wav"},
    )
    assert response.status_code == 200
    assert response.json()["deleted"] is True
    mock_delete.assert_called_once_with(
        "org-1",
        "clip-1",
        "hold-audio/org-1/clip-1/hold.wav",
    )
