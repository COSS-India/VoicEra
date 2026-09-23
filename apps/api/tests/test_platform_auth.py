"""Platform-owned provider credentials and the org-first resolution order."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from app.services import platform_auth
from app.services.platform_auth import PlatformAuthConfigError


def _set_env(monkeypatch, value: str) -> None:
    monkeypatch.setattr(platform_auth.settings, "PLATFORM_PROVIDER_AUTH", value)
    platform_auth._credentials.cache_clear()


def _stored(auth: dict[str, Any] | None):
    """Stand-in for auth_service.get_provider_auth."""

    def _get(org_id: str, provider: str) -> dict[str, Any] | None:
        if auth is None:
            return None
        return {"org_id": org_id, "provider": provider, "auth": dict(auth)}

    return _get


def teardown_function() -> None:
    platform_auth._credentials.cache_clear()


def test_unset_is_a_no_op(monkeypatch):
    _set_env(monkeypatch, "")
    assert platform_auth.providers() == frozenset()
    with patch(
        "app.services.platform_auth.auth_service.get_provider_auth",
        side_effect=_stored(None),
    ):
        assert platform_auth.resolve("org-1", "openai") is None


def test_org_credentials_win_over_platform(monkeypatch):
    _set_env(monkeypatch, json.dumps({"openai": {"api_key": "platform-key"}}))
    with patch(
        "app.services.platform_auth.auth_service.get_provider_auth",
        side_effect=_stored({"api_key": "org-key"}),
    ):
        resolved = platform_auth.resolve("org-1", "openai")
    assert resolved == ({"api_key": "org-key"}, "org")


def test_platform_fills_the_gap(monkeypatch):
    _set_env(monkeypatch, json.dumps({"openai": {"api_key": "platform-key"}}))
    with patch(
        "app.services.platform_auth.auth_service.get_provider_auth",
        side_effect=_stored(None),
    ):
        resolved = platform_auth.resolve("org-1", "openai")
    assert resolved == ({"api_key": "platform-key"}, "platform")
    assert platform_auth.providers() == frozenset({"openai"})


def test_provider_without_platform_entry_is_unresolved(monkeypatch):
    _set_env(monkeypatch, json.dumps({"openai": {"api_key": "platform-key"}}))
    with patch(
        "app.services.platform_auth.auth_service.get_provider_auth",
        side_effect=_stored(None),
    ):
        assert platform_auth.resolve("org-1", "deepgram") is None


def test_resolve_does_not_leak_the_cached_dict(monkeypatch):
    """A caller mutating the returned auth must not corrupt the process cache."""
    _set_env(monkeypatch, json.dumps({"openai": {"api_key": "platform-key"}}))
    with patch(
        "app.services.platform_auth.auth_service.get_provider_auth",
        side_effect=_stored(None),
    ):
        auth, _ = platform_auth.resolve("org-1", "openai")
        auth["api_key"] = "mutated"
        again, _ = platform_auth.resolve("org-1", "openai")
    assert again["api_key"] == "platform-key"


@pytest.mark.parametrize(
    "value",
    [
        "not json",
        json.dumps(["openai"]),
        json.dumps({"openai": "sk-not-an-object"}),
        json.dumps({"does-not-exist": {"api_key": "x"}}),
        json.dumps({"google": {"project_id": "not-a-secret"}}),
        json.dumps({"openai": {}}),
    ],
    ids=[
        "malformed-json",
        "not-an-object",
        "provider-value-not-an-object",
        "unknown-provider",
        "non-secret-field",
        "empty-auth",
    ],
)
def test_bad_config_aborts_startup(monkeypatch, value):
    _set_env(monkeypatch, value)
    with pytest.raises(PlatformAuthConfigError):
        platform_auth.validate_config()


def test_validate_config_accepts_a_good_blob(monkeypatch):
    _set_env(monkeypatch, json.dumps({"openai": {"api_key": "platform-key"}}))
    platform_auth.validate_config()
    assert platform_auth.providers() == frozenset({"openai"})
