"""Plivo recording webhook tests. Ingest is mocked — no live Plivo calls."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

_mock_runners = MagicMock()
_mock_runners.run_telephony_bot = AsyncMock()
_mock_runners.run_websocket_bot = AsyncMock()
sys.modules.setdefault(
    "apps.runtime.services.pipecat.runners",
    _mock_runners,
)

from apps.runtime.routes import plivo_telephony  # noqa: E402


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(plivo_telephony.router)
    return app


@pytest.fixture
def client() -> TestClient:
    return TestClient(_app())


def test_plivo_webhook_missing_call_uuid(client: TestClient) -> None:
    response = client.post("/plivo/recording-webhook", data={"foo": "bar"})
    assert response.status_code == 400


def test_plivo_webhook_downloads_then_ingests(client: TestClient) -> None:
    with (
        patch(
            "apps.runtime.routes.plivo_telephony._load_plivo_client",
            new=AsyncMock(return_value=object()),
        ),
        patch(
            "apps.runtime.routes.plivo_telephony.download_ready_recording",
            new=AsyncMock(
                return_value=(b"ID3", "https://media.plivo.com/rec.mp3")
            ),
        ) as download,
        patch(
            "apps.runtime.routes.plivo_telephony.ingest_provider_recording",
            new=AsyncMock(return_value=JSONResponse({"status": "ok", "call_id": "c1"})),
        ) as ingest,
    ):
        response = client.post(
            "/plivo/recording-webhook",
            data={
                "call_uuid": "uuid-1",
                "record_url": "https://media.plivo.com/rec.mp3",
                "recording_id": "rec-1",
            },
        )
    assert response.status_code == 200
    download.assert_awaited_once()
    assert download.await_args.kwargs["call_uuid"] == "uuid-1"
    assert download.await_args.kwargs["recording_id"] == "rec-1"
    ref = ingest.await_args.args[0]
    assert ref.provider_call_sid == "uuid-1"
    assert ingest.await_args.kwargs["audio"] == b"ID3"


def test_plivo_webhook_polls_when_url_missing(client: TestClient) -> None:
    with (
        patch(
            "apps.runtime.routes.plivo_telephony._load_plivo_client",
            new=AsyncMock(return_value=object()),
        ),
        patch(
            "apps.runtime.routes.plivo_telephony.download_ready_recording",
            new=AsyncMock(return_value=(b"ID3", "https://media.plivo.com/rec.mp3")),
        ) as download,
        patch(
            "apps.runtime.routes.plivo_telephony.ingest_provider_recording",
            new=AsyncMock(return_value=JSONResponse({"status": "ok"})),
        ),
    ):
        response = client.post(
            "/plivo/recording-webhook",
            data={"call_uuid": "uuid-1"},
        )
    assert response.status_code == 200
    assert download.await_args.kwargs["recording_url"] is None
