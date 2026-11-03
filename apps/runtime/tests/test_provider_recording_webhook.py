"""VI recording webhook + shared ingest tests."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_mock_runners = MagicMock()
_mock_runners.run_telephony_bot = AsyncMock()
_mock_runners.run_websocket_bot = AsyncMock()
sys.modules.setdefault(
    "apps.runtime.services.pipecat.runners",
    _mock_runners,
)

from apps.runtime.routes import vi_telephony  # noqa: E402
from apps.runtime.services.backend import BackendError  # noqa: E402


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(vi_telephony.router)
    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_app())


def test_webhook_missing_recording_url(client: TestClient) -> None:
    response = client.post("/vi/recording-webhook", data={"foo": "bar"})
    assert response.status_code == 400
    assert "recording_url" in response.text


def test_webhook_missing_call_id_in_url(client: TestClient) -> None:
    response = client.post(
        "/vi/recording-webhook",
        data={"recording_url": "https://cdn.example/"},
    )
    assert response.status_code == 400
    assert "call id" in response.text.lower()


def test_webhook_unknown_provider_sid(client: TestClient) -> None:
    with patch(
        "apps.runtime.routes.provider_recording.backend_client.get_call_by_provider_sid",
        new=AsyncMock(side_effect=BackendError("Call log not found for provider sid: x")),
    ):
        response = client.post(
            "/vi/recording-webhook",
            data={"recording_url": "https://cdn.example/r.wav?callid=x"},
        )
    assert response.status_code == 404


def test_webhook_download_failure(client: TestClient) -> None:
    with (
        patch(
            "apps.runtime.routes.provider_recording.backend_client.get_call_by_provider_sid",
            new=AsyncMock(
                return_value={"call_id": "call-1", "org_id": "org-1"},
            ),
        ),
        patch(
            "apps.runtime.routes.provider_recording.download_recording_url",
            new=AsyncMock(return_value=None),
        ),
    ):
        response = client.post(
            "/vi/recording-webhook",
            data={"recording_url": "https://cdn.example/r.wav?callid=sid-1"},
        )
    assert response.status_code == 502


def test_webhook_happy_path(client: TestClient) -> None:
    with (
        patch(
            "apps.runtime.routes.provider_recording.backend_client.get_call_by_provider_sid",
            new=AsyncMock(
                return_value={"call_id": "call-1", "org_id": "org-1"},
            ),
        ),
        patch(
            "apps.runtime.routes.provider_recording.download_recording_url",
            new=AsyncMock(return_value=b"RIFFDATA"),
        ),
        patch(
            "apps.runtime.routes.provider_recording.save_and_link",
            new=AsyncMock(return_value=True),
        ) as save,
    ):
        response = client.post(
            "/vi/recording-webhook",
            json={"recording_url": "https://cdn.example/r.wav?callid=sid-1"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["call_id"] == "call-1"
    assert body["provider_call_sid"] == "sid-1"
    save.assert_awaited_once()
    kwargs = save.await_args.kwargs
    assert kwargs["url_field"] == "provider_recording_url"
    assert kwargs["filename"] == "provider_recording.wav"
    assert kwargs["data"] == b"RIFFDATA"
