"""Campaign analytics aggregation and route tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.routers import campaign as campaign_router
from app.services.campaign.campaign_analytics import get_campaign_analytics
from app.services.campaign.campaign_repository import CampaignNotFoundError


def _admin() -> dict[str, Any]:
    return {"email": "admin@example.com", "org_id": "org-1", "role": "admin"}


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(campaign_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = _admin
    return TestClient(app)


def test_get_campaign_analytics_aggregates_dispositions() -> None:
    campaign = {
        "campaign_id": "camp-1",
        "org_id": "org-1",
        "name": "Spring",
        "state": "running",
        "total_rows": 10,
        "processed_rows": 8,
        "failed_rows": 1,
    }
    aggregate_result = {
        "attempted": [{"count": 5}],
        "connected": [
            {
                "count": 2,
                "total_duration": 90.0,
                "average_duration": 45.0,
            }
        ],
        "by_call_response": [
            {"_id": "answered", "count": 2},
            {"_id": "busy", "count": 1},
            {"_id": "no_answer", "count": 1},
            {"_id": "failed", "count": 1},
        ],
    }

    with (
        patch(
            "app.services.campaign.campaign_analytics.repo.get_campaign_for_org",
            return_value=campaign,
        ),
        patch("app.services.campaign.campaign_analytics.get_database") as get_db,
    ):
        coll = MagicMock()
        coll.aggregate.return_value = iter([aggregate_result])
        get_db.return_value = {"CallLogs": coll}

        result = get_campaign_analytics("org-1", "camp-1")

    assert result["campaign_id"] == "camp-1"
    assert result["calls_attempted"] == 5
    assert result["calls_connected"] == 2
    assert result["calls_busy"] == 1
    assert result["calls_no_answer"] == 1
    assert result["calls_failed"] == 1
    assert result["connection_rate"] == 40.0
    assert result["average_duration_seconds"] == 45.0
    assert result["by_call_response"]["answered"] == 2
    assert result["progress_percentage"] == 80.0
    assert result["processed_rows"] == 8


def test_get_campaign_analytics_not_found() -> None:
    with patch(
        "app.services.campaign.campaign_analytics.repo.get_campaign_for_org",
        side_effect=CampaignNotFoundError("missing"),
    ):
        with pytest.raises(CampaignNotFoundError):
            get_campaign_analytics("org-1", "missing")


def test_analytics_route(client: TestClient) -> None:
    payload = {
        "campaign_id": "camp-1",
        "state": "running",
        "total_rows": 10,
        "processed_rows": 5,
        "failed_rows": 0,
        "progress_percentage": 50.0,
        "calls_attempted": 4,
        "calls_connected": 2,
        "calls_busy": 1,
        "calls_no_answer": 1,
        "calls_failed": 0,
        "calls_cancelled": 0,
        "connection_rate": 50.0,
        "total_duration_seconds": 60.0,
        "average_duration_seconds": 30.0,
        "by_call_response": {"answered": 2, "busy": 1, "no_answer": 1},
    }
    with patch(
        "app.routers.campaign.get_campaign_analytics",
        return_value=payload,
    ):
        response = client.get("/api/v1/campaign/camp-1/analytics")
    assert response.status_code == 200
    body = response.json()
    assert body["calls_attempted"] == 4
    assert body["connection_rate"] == 50.0
    assert body["by_call_response"]["answered"] == 2


def test_analytics_route_404(client: TestClient) -> None:
    with patch(
        "app.routers.campaign.get_campaign_analytics",
        side_effect=CampaignNotFoundError("camp-x"),
    ):
        response = client.get("/api/v1/campaign/camp-x/analytics")
    assert response.status_code == 404


def test_campaign_runs_paginated_response(client: TestClient) -> None:
    logs = [
        {
            "call_id": "c1",
            "org_id": "org-1",
            "agent_id": "a1",
            "call_type": "outbound",
            "status": "completed",
            "call_response": "answered",
            "from_number": "+1",
            "to_number": "+2",
            "custom_variables": {},
            "campaign_id": "camp-1",
        }
    ]
    with (
        patch("app.routers.campaign.repo.get_campaign_for_org", return_value={"campaign_id": "camp-1"}),
        patch("app.routers.campaign.list_call_logs_by_campaign", return_value=logs),
        patch("app.routers.campaign.count_call_logs", return_value=1),
    ):
        response = client.get(
            "/api/v1/campaign/camp-1/runs?call_response=answered&limit=10"
        )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 10
    assert len(body["calls"]) == 1
    assert body["calls"][0]["call_id"] == "c1"


def test_campaign_report_includes_extra_columns(client: TestClient) -> None:
    logs = [
        {
            "call_id": "c1",
            "org_id": "org-1",
            "agent_id": "a1",
            "call_type": "outbound",
            "status": "completed",
            "call_response": "answered",
            "from_number": "+15550001",
            "to_number": "+15550002",
            "duration": 12.0,
            "created_at": "2026-01-01T00:00:00+00:00",
            "recording_url": "minio://bucket/rec.wav",
            "transcript_url": "minio://bucket/tr.txt",
            "custom_variables": {},
            "campaign_id": "camp-1",
        }
    ]
    with (
        patch("app.routers.campaign.repo.get_campaign_for_org", return_value={"campaign_id": "camp-1"}),
        patch("app.routers.campaign.list_call_logs_by_campaign", return_value=logs),
    ):
        response = client.get("/api/v1/campaign/camp-1/report")
    assert response.status_code == 200
    text = response.text
    assert "campaign_id" in text
    assert "agent_id" in text
    assert "from_number" in text
    assert "recording_url" in text
    assert "c1" in text
    assert "camp-1" in text
