"""OBD report and status routes call a client method only when it exists."""

from __future__ import annotations

import io
import zipfile
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.routers import campaign as campaign_router


def _admin() -> dict[str, Any]:
    return {"email": "admin@example.com", "org_id": "org-1", "role": "admin"}


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(campaign_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = _admin
    return TestClient(app)


def _campaign() -> dict[str, Any]:
    return {
        "campaign_id": "camp-1",
        "org_id": "org-1",
        "telephony_provider": "vi",
        "from_number": "1600413975",
        "started_at": "2026-10-27T08:00:00+00:00",
        "orchestrator_metadata": {"bulk_obd_campaign_ids": ["761022"]},
    }


class _ObdClient:
    async def get_obd_report(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["from_number"] == "1600413975"
        return {
            "status": "success",
            "summary": {
                "attempted": 1,
                "connected": 1,
                "timeout": 0,
                "line_drop": 0,
                "connection_rate": 100.0,
                "average_duration_seconds": 63.0,
            },
            "rows": [
                {
                    "phone": "9823526077",
                    "dial_status": "Connected",
                    "when": "27/10/2026 14:24:00",
                    "duration_seconds": 63,
                    "recording_url": "https://cts.example/rec",
                    "provider_call_id": "40199559",
                    "circle": "TN",
                    "operator": "Vi",
                    "campaign_id": "761022",
                    "campaign_name": "campaign-demo",
                }
            ],
        }

    async def get_obd_status(self, **kwargs: Any) -> dict[str, Any]:
        assert kwargs["metadata"]["bulk_obd_campaign_ids"] == ["761022"]
        return {
            "status": "success",
            "statuses": [
                {
                    "campaign_id": "761022",
                    "campaign_name": "Oldxr",
                    "current_status": "Campaign finished",
                    "total_base_received": 1,
                    "remaining_in_queue": 0,
                }
            ],
        }


class _PlainClient:
    pass


def test_obd_report_and_csv(client: TestClient) -> None:
    with (
        patch(
            "app.routers.campaign.repo.get_campaign_for_org",
            return_value=_campaign(),
        ),
        patch(
            "app.routers.campaign.load_telephony_client",
            return_value=_ObdClient(),
        ),
        patch(
            "app.routers.campaign.get_call_log_by_provider_sid",
            return_value=None,
        ),
    ):
        report = client.get("/api/v1/campaign/camp-1/obd-report")
        csv_response = client.get("/api/v1/campaign/camp-1/obd-report?format=csv")

    assert report.status_code == 200
    body = report.json()
    assert body["summary"]["attempted"] == 1
    assert body["rows"][0]["recording_url"] == "https://cts.example/rec"

    assert csv_response.status_code == 200
    assert "text/csv" in csv_response.headers["content-type"]
    text = csv_response.text
    assert "system_call_id" in text
    assert "recording_url" in text
    assert "https://cts.example/rec" in text
    assert "9823526077" in text


def test_obd_report_zip_includes_saved_transcript(client: TestClient) -> None:
    def lookup(org_id: str, provider_call_sid: str) -> dict[str, str] | None:
        assert org_id == "org-1"
        if provider_call_sid != "40199559":
            return None
        return {
            "call_id": "6dcd41e3-a750-4ba2-9cbd-f912edaccec1",
            "transcript_url": "minio://voicera-calls/org-1/call-1/transcript.txt",
        }

    with (
        patch(
            "app.routers.campaign.repo.get_campaign_for_org",
            return_value=_campaign(),
        ),
        patch(
            "app.routers.campaign.load_telephony_client",
            return_value=_ObdClient(),
        ),
        patch(
            "app.routers.campaign.get_call_log_by_provider_sid",
            side_effect=lookup,
        ),
        patch(
            "app.routers.campaign.MinIOStorage.get_object_bytes",
            new=AsyncMock(return_value=b"agent: hello"),
        ),
    ):
        response = client.get("/api/v1/campaign/camp-1/obd-report?format=zip")

    assert response.status_code == 200
    assert "application/zip" in response.headers["content-type"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = set(archive.namelist())
        call_file = "calls/6dcd41e3-a750-4ba2-9cbd-f912edaccec1.txt"
        assert "csv/obd-report-camp-1.csv" in names
        assert call_file in names
        csv_text = archive.read("csv/obd-report-camp-1.csv").decode()
        assert "system_call_id" in csv_text
        assert "6dcd41e3-a750-4ba2-9cbd-f912edaccec1" in csv_text
        body = archive.read(call_file).decode()
        assert "provider_call_id: 40199559" in body
        assert "system_call_id: 6dcd41e3-a750-4ba2-9cbd-f912edaccec1" in body
        assert "recording_url: https://cts.example/rec" in body
        assert "agent: hello" in body


def test_obd_status(client: TestClient) -> None:
    with (
        patch(
            "app.routers.campaign.repo.get_campaign_for_org",
            return_value=_campaign(),
        ),
        patch(
            "app.routers.campaign.load_telephony_client",
            return_value=_ObdClient(),
        ),
    ):
        response = client.get("/api/v1/campaign/camp-1/obd-status")
    assert response.status_code == 200
    status = response.json()["statuses"][0]
    assert status["current_status"] == "Campaign finished"
    assert status["campaign_name"] == "Oldxr"


def test_obd_report_404_when_client_has_no_method(client: TestClient) -> None:
    with (
        patch(
            "app.routers.campaign.repo.get_campaign_for_org",
            return_value=_campaign(),
        ),
        patch(
            "app.routers.campaign.load_telephony_client",
            return_value=_PlainClient(),
        ),
    ):
        response = client.get("/api/v1/campaign/camp-1/obd-report")
    assert response.status_code == 404


def test_obd_report_409_when_credentials_missing(client: TestClient) -> None:
    class _Missing:
        async def get_obd_report(self, **kwargs: Any) -> dict[str, Any]:
            del kwargs
            return {
                "status": "fail",
                "message": "Pull API credentials are not configured",
                "code": "missing_credentials",
            }

    with (
        patch(
            "app.routers.campaign.repo.get_campaign_for_org",
            return_value=_campaign(),
        ),
        patch(
            "app.routers.campaign.load_telephony_client",
            return_value=_Missing(),
        ),
    ):
        response = client.get("/api/v1/campaign/camp-1/obd-report")
    assert response.status_code == 409
    assert response.json()["detail"] == "Pull API credentials are not configured"
