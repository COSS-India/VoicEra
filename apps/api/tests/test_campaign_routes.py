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
