"""Campaign API route tests."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.routers import campaign as campaign_router
from app.services.agent_service import AgentNotFoundError


def _admin() -> dict[str, Any]:
    return {"email": "admin@example.com", "org_id": "org-1", "role": "admin"}


@pytest.fixture
def client() -> TestClient:
    app = FastAPI()
    app.include_router(campaign_router.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = _admin
    return TestClient(app)


def test_upload_campaign_csv(client: TestClient) -> None:
    csv_body = b"phone_number,customer_name\n+14155551234,Jane\n"
    with (
        patch("app.routers.campaign.MinIOStorage") as storage_cls,
        patch("app.routers.campaign.get_sync_service") as sync_factory,
    ):
        storage_cls.return_value.put_object_bytes = AsyncMock()
        sync_service = AsyncMock()
        sync_service.validate_source.return_value = type(
            "VR",
            (),
            {
                "is_valid": True,
                "error": None,
                "headers": ["phone_number", "customer_name"],
                "rows": [["+14155551234", "Jane"]],
            },
        )()
        sync_factory.return_value = sync_service
        response = client.post(
            "/api/v1/campaign/upload",
            files={"file": ("contacts.csv", csv_body, "text/csv")},
        )
    assert response.status_code == 201
    body = response.json()
    assert body["source_id"].startswith("campaigns/org-1/")
    assert body["contact_rows"] == 1


def test_upload_campaign_csv_rejects_non_csv(client: TestClient) -> None:
    response = client.post(
        "/api/v1/campaign/upload",
        files={"file": ("contacts.txt", b"hello", "text/plain")},
    )
    assert response.status_code == 400


def test_create_campaign_validates_agent(client: TestClient) -> None:
    with patch(
        "app.routers.campaign.agent_service.get_agent",
        side_effect=AgentNotFoundError("missing"),
    ):
        response = client.post(
            "/api/v1/campaign/create",
            json={
                "name": "Camp",
                "agent_id": "missing",
                "source_id": "campaigns/org-1/x.csv",
            },
        )
    assert response.status_code == 404


def test_create_campaign_stores_obd_config(client: TestClient) -> None:
    captured: dict[str, Any] = {}

    def _create(doc: dict[str, Any]) -> dict[str, Any]:
        captured.update(doc)
        return {
            **doc,
            "campaign_id": "camp-obd-1",
            "state": "created",
            "total_rows": 0,
            "processed_rows": 0,
            "failed_rows": 0,
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }

    with (
        patch(
            "app.routers.campaign.agent_service.get_agent",
            return_value={
                "agent_id": "agent-1",
                "agent_category": "telephony",
                "telephony": {"provider": "vi"},
                "linked_phone_number": "+919876543210",
            },
        ),
        patch("app.routers.campaign._count_agent_from_numbers", return_value=1),
        patch("app.routers.campaign.get_org_concurrent_limit", return_value=20),
        patch("app.routers.campaign.get_sync_service") as sync_factory,
        patch("app.routers.campaign.repo.create_campaign", side_effect=_create),
    ):
        sync_service = AsyncMock()
        sync_service.validate_source.return_value = type(
            "VR",
            (),
            {"is_valid": True, "error": None, "headers": [], "rows": []},
        )()
        sync_factory.return_value = sync_service
        response = client.post(
            "/api/v1/campaign/create",
            json={
                "name": "VI Camp",
                "agent_id": "agent-1",
                "source_id": "campaigns/org-1/x.csv",
                "obd_config": {
                    "description": "Kharif OBD",
                    "fromdate": "2026-10-15",
                    "todate": "2026-10-15",
                    "fromtime": "10:00:00",
                    "totime": "18:00:00",
                    "dialtimeout": 45,
                    "retrycount": 2,
                    "retryintervalvalue": 10,
                    "retryintervaltype": 0,
                },
            },
        )
    assert response.status_code == 201
    obd = captured.get("orchestrator_metadata", {}).get("obd_config")
    assert obd is not None
    assert obd["description"] == "Kharif OBD"
    assert obd["fromdate"] == "2026-10-15"
    assert obd["dialtimeout"] == 45
    assert obd["retrycount"] == 2
    assert obd["retryintervalvalue"] == 10
