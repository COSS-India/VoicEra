"""Bot service token exchange under /users."""

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import auth, users


@patch(
    "app.routers.users.org_service.get_organisation",
    side_effect=lambda org_id: (
        {"org_id": org_id, "name": "Test"} if org_id == "org-1" else None
    ),
)
def test_bot_token_returns_access_token(_org_m, monkeypatch):
    from app import auth as auth_mod
    from app.auth import verify_token

    monkeypatch.setattr(auth_mod.settings, "INTERNAL_API_KEY", "test-internal-key")

    app = FastAPI()
    app.include_router(users.router, prefix="/api/v1")
    app.include_router(auth.router, prefix="/api/v1")
    client = TestClient(app)

    missing = client.post("/api/v1/users/bot/token", json={"org_id": "org-1"})
    assert missing.status_code == 401

    wrong = client.post(
        "/api/v1/users/bot/token",
        json={"org_id": "org-1"},
        headers={"X-API-Key": "wrong"},
    )
    assert wrong.status_code == 401

    ok = client.post(
        "/api/v1/users/bot/token",
        json={"org_id": "org-1"},
        headers={"X-API-Key": "test-internal-key"},
    )
    assert ok.status_code == 200
    body = ok.json()
    assert set(body) == {"access_token", "token_type", "org_id", "role"}
    assert body["token_type"] == "bearer"
    assert body["org_id"] == "org-1"
    assert body["role"] == "admin"
    payload = verify_token(body["access_token"])
    assert payload is not None
    assert payload["org_id"] == "org-1"
    assert payload["role"] == "admin"
    assert payload["sub"] == "bot@voicera.internal"

    with patch(
        "app.routers.auth.auth_service.list_configured_providers",
        return_value=["openai"],
    ):
        configured = client.get(
            "/api/v1/auth/configured",
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )
    assert configured.status_code == 200
    assert configured.json() == ["openai"]

    missing_org = client.post(
        "/api/v1/users/bot/token",
        json={"org_id": "org-missing"},
        headers={"X-API-Key": "test-internal-key"},
    )
    assert missing_org.status_code == 404


def test_legacy_auth_bot_get_removed(monkeypatch):
    from app import auth as auth_mod

    monkeypatch.setattr(auth_mod.settings, "INTERNAL_API_KEY", "test-internal-key")
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")
    client = TestClient(app)
    response = client.post(
        "/api/v1/auth/bot/get",
        json={"org_id": "org-1"},
        headers={"X-API-Key": "test-internal-key"},
    )
    assert response.status_code == 404
