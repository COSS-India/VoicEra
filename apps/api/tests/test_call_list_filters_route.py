"""Org call list filter query-param route tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.routers import calls
from app.services.call_log_service import CallLogListFilters


def _admin() -> dict[str, Any]:
    return {"email": "admin@example.com", "org_id": "org-1", "role": "admin"}


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(calls.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = _admin
    return TestClient(app)


@patch(
    "app.routers.calls.org_service.get_organisation",
    return_value={"org_id": "org-1", "name": "Org"},
)
@patch("app.routers.calls.count_call_logs", return_value=1)
@patch("app.routers.calls.list_call_logs_by_org")
def test_list_org_calls_passes_campaign_filter(
    list_fn: MagicMock,
    _count: MagicMock,
    _org: MagicMock,
) -> None:
    list_fn.return_value = [
        {
            "call_id": "c1",
            "org_id": "org-1",
            "agent_id": "a1",
            "agent_name": "Agent",
            "call_type": "outbound",
            "status": "completed",
            "from_number": "+1",
            "to_number": "+2",
            "custom_variables": {},
            "campaign_id": "camp-1",
            "campaign_name": "Spring",
        }
    ]
    response = _client().get(
        "/api/v1/calls/org/org-1?campaign_id=camp-1&status=completed&call_type=outbound"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["calls"][0]["campaign_name"] == "Spring"

    filters: CallLogListFilters = list_fn.call_args.kwargs["filters"]
    assert filters.campaign_id == "camp-1"
    assert filters.status == "completed"
    assert filters.call_type == "outbound"
    assert filters.exclude_campaign is False


@patch(
    "app.routers.calls.org_service.get_organisation",
    return_value={"org_id": "org-1", "name": "Org"},
)
@patch("app.routers.calls.count_call_logs", return_value=0)
@patch("app.routers.calls.list_call_logs_by_org", return_value=[])
def test_list_org_calls_exclude_campaign(
    list_fn: MagicMock,
    _count: MagicMock,
    _org: MagicMock,
) -> None:
    response = _client().get("/api/v1/calls/org/org-1?exclude_campaign=true")
    assert response.status_code == 200
    filters: CallLogListFilters = list_fn.call_args.kwargs["filters"]
    assert filters.exclude_campaign is True


@patch(
    "app.routers.calls.org_service.get_organisation",
    return_value={"org_id": "org-1", "name": "Org"},
)
def test_list_org_calls_rejects_combined_campaign_filters(_org: MagicMock) -> None:
    response = _client().get(
        "/api/v1/calls/org/org-1?exclude_campaign=true&campaign_id=camp-1"
    )
    assert response.status_code == 400
