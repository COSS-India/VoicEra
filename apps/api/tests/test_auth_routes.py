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
    from app.services.auth_service import mask_auth_secrets

    return {
        "org_id": org_id,
        "provider": provider,
        "auth": mask_auth_secrets(provider, validated),
        "created_at": doc["created_at"],
        "updated_at": doc["updated_at"],
    }


def _get(org_id: str, provider: str) -> dict[str, Any] | None:
    """Stand-in for the unmasked service call (internal route only)."""
    doc = _STORE.get((org_id, provider))
    if not doc:
        return None
    return {
        "org_id": doc["org_id"],
        "provider": doc["provider"],
        "auth": dict(doc["auth"]),
        "created_at": doc["created_at"],
        "updated_at": doc["updated_at"],
    }


def _get_masked(org_id: str, provider: str) -> dict[str, Any] | None:
    from app.services.auth_service import mask_auth_secrets

    stored = _get(org_id, provider)
    if not stored:
        return None
    return {**stored, "auth": mask_auth_secrets(provider, stored["auth"])}


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
@patch("app.routers.auth.auth_service.get_provider_auth_masked", side_effect=_get_masked)
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
    # The key just sent is never echoed back, not even to the admin who set it.
    assert created.json()["auth"]["api_key"] == "**************1234"

    configured = client.get("/api/v1/auth/configured")
    assert configured.status_code == 200
    assert configured.json() == ["openai"]

    fetched = client.get("/api/v1/auth/openai")
    assert fetched.status_code == 200
    assert fetched.json()["auth"]["api_key"] == "**************1234"

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
@patch("app.routers.auth.auth_service.get_provider_auth_masked", side_effect=_get_masked)
def test_every_role_sees_masked_secrets(_get_m, _upsert_m):
    """Role is not a boundary here: a sandbox signup is super_admin of its org."""
    admin = _make_client(_admin_user)
    admin.post(
        "/api/v1/auth",
        json={"provider": "openai", "auth": {"api_key": "sk-secret-key-1234"}},
    )
    for client in (admin, _make_client(_member_user)):
        response = client.get("/api/v1/auth/openai")
        assert response.status_code == 200
        key = response.json()["auth"]["api_key"]
        assert key.endswith("1234")
        assert key.startswith("*")
        assert "sk-secret" not in key


@patch("app.routers.auth.auth_service.upsert_provider_auth", side_effect=_upsert)
@patch("app.services.platform_auth.auth_service.get_provider_auth", side_effect=_get)
def test_internal_route_returns_plaintext_for_api_key(_get_m, _upsert_m, monkeypatch):
    from app import auth as auth_mod

    monkeypatch.setattr(auth_mod.settings, "INTERNAL_API_KEY", "test-internal-key")
    admin = _make_client(_admin_user)
    admin.post(
        "/api/v1/auth",
        json={"provider": "openai", "auth": {"api_key": "sk-secret-key-1234"}},
    )

    url = "/api/v1/auth/internal/openai"
    params = {"org_id": "org-1"}

    assert admin.get(url, params=params).status_code == 401
    assert admin.get(url, params=params, headers={"X-API-Key": "wrong"}).status_code == 401

    ok = admin.get(url, params=params, headers={"X-API-Key": "test-internal-key"})
    assert ok.status_code == 200
    assert ok.json()["auth"]["api_key"] == "sk-secret-key-1234"
    assert ok.json()["source"] == "org"

    missing = admin.get(
        url,
        params={"org_id": "org-unknown"},
        headers={"X-API-Key": "test-internal-key"},
    )
    assert missing.status_code == 404


@patch("app.routers.auth.auth_service.list_configured_providers", side_effect=_configured)
def test_availability_reports_every_source(_cfg_m, monkeypatch):
    """Local providers need no credential — the page must not offer 'Connect'."""
    _STORE[("org-1", "deepgram")] = {"org_id": "org-1", "provider": "deepgram", "auth": {}}
    client = _make_client(_admin_user)

    with (
        patch(
            "app.routers.auth.platform_auth.providers",
            return_value=frozenset({"openai"}),
        ),
        patch(
            "apps.providers.availability._deployed_ids",
            return_value=frozenset({"indic-nemotron"}),
        ),
    ):
        response = client.get("/api/v1/auth/availability")

    assert response.status_code == 200
    body = response.json()
    assert body["deepgram"] == {"source": "org", "provided": False}
    assert body["openai"] == {"source": "platform", "provided": True}
    assert body["indic_nemotron"] == {"source": "local", "provided": True}
    assert body["elevenlabs"] == {"source": None, "provided": False}


@patch("app.routers.auth.auth_service.list_configured_providers", side_effect=_configured)
def test_availability_keeps_provided_visible_under_an_org_key(_cfg_m):
    """Deleting an org key on a platform provider falls back, not disconnects."""
    _STORE[("org-1", "openai")] = {"org_id": "org-1", "provider": "openai", "auth": {}}
    client = _make_client(_admin_user)

    with patch(
        "app.routers.auth.platform_auth.providers",
        return_value=frozenset({"openai"}),
    ):
        body = client.get("/api/v1/auth/availability").json()

    # The org's own key is in effect, but the platform one is still underneath.
    assert body["openai"] == {"source": "org", "provided": True}


def test_internal_route_requires_org_id(monkeypatch):
    from app import auth as auth_mod

    monkeypatch.setattr(auth_mod.settings, "INTERNAL_API_KEY", "test-internal-key")
    client = _make_client(_admin_user)
    response = client.get(
        "/api/v1/auth/internal/openai",
        headers={"X-API-Key": "test-internal-key"},
    )
    assert response.status_code == 422


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
    assert auth_body["api_key"].endswith("-key")
    assert auth_body["api_key"].startswith("*")
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
