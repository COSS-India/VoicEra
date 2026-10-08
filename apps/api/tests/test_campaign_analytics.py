"""Campaign analytics aggregation and route tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.routers import campaign as campaign_router
from app.services.call_log_service import CallLogListFilters, get_call_analytics
from app.services.campaign.campaign_repository import CampaignNotFoundError


def _admin() -> dict[str, Any]:
    return {"email": "admin@example.com", "org_id": "org-1", "role": "admin"}


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(campaign_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = _admin
    return TestClient(app)


def test_get_call_analytics_aggregates_dispositions() -> None:
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

    with patch("app.services.call_log_service.get_database") as get_db:
        coll = MagicMock()
        coll.aggregate.return_value = iter([aggregate_result])
        get_db.return_value = {"CallLogs": coll}

        result = get_call_analytics("org-1", CallLogListFilters(campaign_id="camp-1"))

    assert result["calls_attempted"] == 5
    assert result["calls_connected"] == 2
    assert result["connection_rate"] == 40.0
    assert result["average_duration_seconds"] == 45.0
    assert result["by_call_response"]["answered"] == 2
    assert result["by_call_response"]["busy"] == 1


def test_analytics_route(client: TestClient) -> None:
    campaign = {
        "campaign_id": "camp-1",
        "state": "running",
        "total_rows": 10,
        "processed_rows": 5,
        "failed_rows": 0,
    }
    stats = {
        "calls_attempted": 4,
        "calls_connected": 2,
        "connection_rate": 50.0,
        "total_duration_seconds": 60.0,
        "average_duration_seconds": 30.0,
        "by_call_response": {"answered": 2, "busy": 1, "no_answer": 1},
    }
    with (
        patch(
            "app.routers.campaign.repo.get_campaign_for_org",
            return_value=campaign,
        ),
        patch("app.routers.campaign.get_call_analytics", return_value=stats),
    ):
        response = client.get("/api/v1/campaign/camp-1/analytics")
    assert response.status_code == 200
    body = response.json()
    assert body["calls_attempted"] == 4
    assert body["connection_rate"] == 50.0
    assert body["progress_percentage"] == 50.0
    assert body["by_call_response"]["answered"] == 2
    assert "calls_busy" not in body


def test_analytics_route_404(client: TestClient) -> None:
    with patch(
        "app.routers.campaign.repo.get_campaign_for_org",
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
