"""HTTP mapping for the voice preview route."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.routers import tts_preview
from app.services.tts_preview_service import TtsPreviewError, TtsPreviewErrorReason

app = FastAPI()
app.include_router(tts_preview.router, prefix="/api/v1")
_DEFAULT_USER = {"email": "test@example.com", "org_id": "org-1"}
app.dependency_overrides[get_current_user] = lambda: _DEFAULT_USER

client = TestClient(app)

_BODY = {
    "tts_config": {"provider": "sarvam", "model": "bulbul:v3", "voice": "shubh"},
    "language": "hi",
    "text": "Namaste {{name}}",
}


@patch("app.routers.tts_preview.generate_preview", new_callable=AsyncMock)
def test_preview_returns_wav_audio_on_success(mock_generate):
    # Arrange
    mock_generate.return_value = b"RIFF....WAVEfmt "

    # Act
    response = client.post("/api/v1/tts/preview", json=_BODY)

    # Assert
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.content == b"RIFF....WAVEfmt "


@pytest.mark.parametrize(
    ("reason", "expected_status"),
    [
        (TtsPreviewErrorReason.EMPTY_TEXT, 400),
        (TtsPreviewErrorReason.OVERSIZED, 413),
        (TtsPreviewErrorReason.INVALID_CONFIG, 422),
        (TtsPreviewErrorReason.UNSUPPORTED_VOICE, 422),
        (TtsPreviewErrorReason.NOT_CONFIGURED, 409),
        (TtsPreviewErrorReason.TIMEOUT, 504),
        (TtsPreviewErrorReason.UPSTREAM, 502),
    ],
)
@patch("app.routers.tts_preview.generate_preview", new_callable=AsyncMock)
def test_preview_maps_each_error_reason_to_its_status(mock_generate, reason, expected_status):
    # Arrange
    mock_generate.side_effect = TtsPreviewError(reason, "boom")

    # Act
    response = client.post("/api/v1/tts/preview", json=_BODY)

    # Assert
    assert response.status_code == expected_status


def test_preview_requires_active_org(monkeypatch):
    # Arrange: monkeypatch restores the default user after the test.
    monkeypatch.setitem(
        app.dependency_overrides, get_current_user, lambda: {"email": "no-org@example.com"}
    )

    # Act
    response = client.post("/api/v1/tts/preview", json=_BODY)

    # Assert
    assert response.status_code == 400
