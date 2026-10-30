"""Platform provider credentials: a new org can use a provider it never connected.

The one property that matters most here is that the key is never readable by a
user. Every signup is a super_admin, and GET /auth/{provider} returns stored
secrets unmasked to admins -- so a platform key served the same way would be
handed to anyone who can fill in the signup form.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.config import settings
from app.routers import auth
from app.services import platform_auth

KEY = "sk-platform-test-key-9876"


def _user(email: str, role: str = "super_admin") -> dict[str, Any]:
    return {"email": email, "org_id": "org-new", "role": role}


def _client(user: dict[str, Any]) -> TestClient:
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


@pytest.fixture
def platform(monkeypatch):
    def configure(value: Any) -> None:
        raw = value if isinstance(value, str) else json.dumps(value)
        monkeypatch.setattr(settings, "PLATFORM_PROVIDER_AUTH", raw)
        platform_auth._credentials.cache_clear()
    return configure


def test_unset_means_no_platform_providers():
    assert platform_auth.providers() == frozenset()
    assert platform_auth.get("openai") is None


def test_parses_and_validates(platform):
    platform({"openai": {"api_key": KEY}})
    assert platform_auth.providers() == {"openai"}
    assert platform_auth.get("openai") == {"api_key": KEY}


def test_a_quoted_env_value_still_parses(platform):
    platform("'" + json.dumps({"openai": {"api_key": KEY}}) + "'")
    assert platform_auth.providers() == {"openai"}


@pytest.mark.parametrize("bad", ["{not json", "[]", {"openai": "sk-x"}, {"no-such-provider": {"api_key": "x"}}])
def test_a_bad_value_fails_at_startup(platform, bad):
    platform(bad)
    with pytest.raises(platform_auth.PlatformAuthConfigError):
        platform_auth.validate_config()


def test_telephony_is_refused(platform):
    platform({"vobiz": {"auth_id": "x", "auth_token": "y"}})
    with pytest.raises(platform_auth.PlatformAuthConfigError, match="telephony"):
        platform_auth.validate_config()


@patch("app.routers.auth.auth_service.get_provider_auth", return_value=None)
def test_the_runtime_gets_the_key(_get, platform):
    platform({"openai": {"api_key": KEY}})
    r = _client(_user(platform_auth.BOT_SERVICE_EMAIL, "admin")).get("/api/v1/auth/openai")
    assert r.status_code == 200
    assert r.json()["auth"] == {"api_key": KEY}


@pytest.mark.parametrize("role", ["super_admin", "admin", "member"])
@patch("app.routers.auth.auth_service.get_provider_auth", return_value=None)
def test_users_never_see_it_unmasked(_get, platform, role):
    platform({"openai": {"api_key": KEY}})
    r = _client(_user("someone@example.com", role)).get("/api/v1/auth/openai")
    assert r.status_code == 200
    assert KEY not in r.text
    assert r.json()["auth"]["api_key"].endswith(KEY[-4:])


@patch("app.routers.auth.auth_service.get_provider_auth")
def test_the_orgs_own_key_wins(get, platform):
    platform({"openai": {"api_key": KEY}})
    get.return_value = {"org_id": "org-new", "provider": "openai", "auth": {"api_key": "sk-org-own-1111"}}
    r = _client(_user(platform_auth.BOT_SERVICE_EMAIL, "admin")).get("/api/v1/auth/openai")
    assert r.json()["auth"] == {"api_key": "sk-org-own-1111"}


@patch("app.routers.auth.auth_service.get_provider_auth", return_value=None)
def test_a_provider_with_no_key_anywhere_is_still_404(_get, platform):
    platform({"openai": {"api_key": KEY}})
    r = _client(_user(platform_auth.BOT_SERVICE_EMAIL, "admin")).get("/api/v1/auth/groq")
    assert r.status_code == 404


@patch("app.routers.auth.auth_service.list_configured_providers", return_value=["sarvam"])
def test_configured_includes_platform_providers(_cfg, platform):
    platform({"openai": {"api_key": KEY}})
    r = _client(_user("someone@example.com")).get("/api/v1/auth/configured")
    assert r.json() == ["openai", "sarvam"]
