"""Provider-level auth catalog and credential persistence routes."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.routers import auth

_STORE: dict[tuple[str, str], dict[str, Any]] = {}


def _admin_user() -> dict[str, Any]:
    return {
        "email": "admin@example.com",
        "org_id": "org-1",
        "role": "admin",
    }


def _member_user() -> dict[str, Any]:
    return {
        "email": "member@example.com",
        "org_id": "org-1",
        "role": "member",
    }


def _upsert(org_id: str, provider: str, auth_body: dict[str, Any]) -> dict[str, Any]:
    from app.services.provider_auth_catalog import validate_auth_payload

    validated = validate_auth_payload(provider, auth_body)
    key = (org_id, provider)
    existing = _STORE.get(key)
    now = "2026-01-01T00:00:00+00:00"
    if existing:
        doc = {
            **existing,
            "auth": validated,
            "updated_at": now,
        }
    else:
        doc = {
            "org_id": org_id,
            "provider": provider,
            "auth": validated,
            "created_at": now,
            "updated_at": now,
        }
    _STORE[key] = doc
    return {
        "org_id": org_id,
        "provider": provider,
        "auth": validated,
        "created_at": doc["created_at"],
        "updated_at": doc["updated_at"],
    }


def _get(org_id: str, provider: str, *, mask_secrets: bool = False) -> dict[str, Any] | None:
    from app.services.auth_service import mask_auth_secrets

    doc = _STORE.get((org_id, provider))
    if not doc:
        return None
    auth_body = dict(doc["auth"])
    if mask_secrets:
        auth_body = mask_auth_secrets(provider, auth_body)
    return {
        "org_id": doc["org_id"],
        "provider": doc["provider"],
        "auth": auth_body,
        "created_at": doc["created_at"],
        "updated_at": doc["updated_at"],
    }


def _configured(org_id: str) -> list[str]:
    return sorted(p for (o, p) in _STORE if o == org_id)


def _delete(org_id: str, provider: str) -> bool:
    return _STORE.pop((org_id, provider), None) is not None


def _make_client(user_factory) -> TestClient:
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = user_factory
    return TestClient(app)


def setup_function() -> None:
    _STORE.clear()


def test_auth_catalog_flat_by_provider():
    client = _make_client(_admin_user)
    response = client.get("/api/v1/auth/catalog")
    assert response.status_code == 200
    body = response.json()
    assert "openai" in body
    assert "vobiz" in body
    assert "stt" not in body  # flat by provider, not nested by kind
    openai = body["openai"]
    assert set(openai["kinds"]) == {"stt", "tts", "llm"}
    assert "api_key" in openai["fields"]


def test_auth_catalog_google_merges_field_families():
    client = _make_client(_admin_user)
    response = client.get("/api/v1/auth/catalog/google")
    assert response.status_code == 200
    fields = response.json()["fields"]
    assert "api_key" in fields
    assert "credentials" in fields
    assert "project_id" in fields


def test_auth_catalog_unknown_provider_404():
    client = _make_client(_admin_user)
    response = client.get("/api/v1/auth/catalog/does-not-exist")
    assert response.status_code == 404


@patch("app.routers.auth.auth_service.upsert_provider_auth", side_effect=_upsert)
@patch("app.routers.auth.auth_service.get_provider_auth", side_effect=_get)
@patch("app.routers.auth.auth_service.list_configured_providers", side_effect=_configured)
@patch("app.routers.auth.auth_service.delete_provider_auth", side_effect=_delete)
def test_post_get_configured_delete_flow(_delete_m, _cfg_m, _get_m, _upsert_m):
    client = _make_client(_admin_user)

    created = client.post(
        "/api/v1/auth",
        json={"provider": "openai", "auth": {"api_key": "sk-secret-key-1234"}},
    )
    assert created.status_code == 201
    assert created.json()["provider"] == "openai"
    assert created.json()["auth"]["api_key"] == "sk-secret-key-1234"

    configured = client.get("/api/v1/auth/configured")
    assert configured.status_code == 200
    assert configured.json() == ["openai"]

    fetched = client.get("/api/v1/auth/openai")
    assert fetched.status_code == 200
    assert fetched.json()["auth"]["api_key"] == "sk-secret-key-1234"

    deleted = client.delete("/api/v1/auth/openai")
    assert deleted.status_code == 200
    assert client.get("/api/v1/auth/configured").json() == []
    assert client.get("/api/v1/auth/openai").status_code == 404


@patch("app.routers.auth.auth_service.upsert_provider_auth", side_effect=_upsert)
def test_member_cannot_write(_upsert_m):
    client = _make_client(_member_user)
    response = client.post(
        "/api/v1/auth",
        json={"provider": "openai", "auth": {"api_key": "sk-test"}},
    )
    assert response.status_code == 403


@patch("app.routers.auth.auth_service.upsert_provider_auth", side_effect=_upsert)
@patch("app.routers.auth.auth_service.get_provider_auth", side_effect=_get)
def test_member_sees_masked_secrets(_get_m, _upsert_m):
    admin = _make_client(_admin_user)
    admin.post(
        "/api/v1/auth",
        json={"provider": "openai", "auth": {"api_key": "sk-secret-key-1234"}},
    )
    member = _make_client(_member_user)
    response = member.get("/api/v1/auth/openai")
    assert response.status_code == 200
    key = response.json()["auth"]["api_key"]
    assert key.endswith("1234")
    assert key.startswith("*")


@patch("app.routers.auth.auth_service.upsert_provider_auth", side_effect=_upsert)
def test_google_accepts_secret_fields_only(_upsert_m):
    client = _make_client(_admin_user)
    response = client.post(
        "/api/v1/auth",
        json={
            "provider": "google",
            "auth": {
                "api_key": "ai-studio-key",
                "credentials": '{"type":"service_account"}',
            },
        },
    )
    assert response.status_code == 201
    auth_body = response.json()["auth"]
    assert auth_body["api_key"] == "ai-studio-key"
    assert "credentials" in auth_body
    assert "project_id" not in auth_body


@patch("app.routers.auth.auth_service.upsert_provider_auth", side_effect=_upsert)
def test_google_rejects_non_secret_project_id(_upsert_m):
    client = _make_client(_admin_user)
    response = client.post(
        "/api/v1/auth",
        json={
            "provider": "google",
            "auth": {
                "api_key": "ai-studio-key",
                "project_id": "my-project",
            },
        },
    )
    assert response.status_code == 422


@patch("app.routers.auth.auth_service.upsert_provider_auth", side_effect=_upsert)
def test_unknown_auth_field_is_422(_upsert_m):
    client = _make_client(_admin_user)
    response = client.post(
        "/api/v1/auth",
        json={"provider": "openai", "auth": {"api_key": "sk", "extra": "nope"}},
    )
    assert response.status_code == 422
