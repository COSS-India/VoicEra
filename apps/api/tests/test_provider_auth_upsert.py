"""Upsert semantics for stored provider credentials.

Clients only ever see masked secrets, so they cannot resend what they did not
change. An update must therefore merge rather than replace.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from app.services import auth_service
from app.services.secret_crypto import decrypt_json, encrypt_json


class _FakeProviderAuth:
    def __init__(self) -> None:
        self.docs: list[dict[str, Any]] = []

    def find_one(self, query: dict[str, Any]) -> dict[str, Any] | None:
        for doc in self.docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return doc
        return None

    def insert_one(self, doc: dict[str, Any]) -> None:
        self.docs.append(dict(doc))

    def update_one(self, query: dict[str, Any], update: dict[str, Any]) -> None:
        doc = self.find_one(query)
        assert doc is not None
        doc.update(update["$set"])


@pytest.fixture
def collection(monkeypatch):
    from app import config as config_mod
    from app.config import get_settings
    from app.services import secret_crypto as crypto_mod

    monkeypatch.setenv(
        "PROVIDER_AUTH_ENCRYPTION_KEY",
        Fernet.generate_key().decode(),
    )
    get_settings.cache_clear()
    config_mod.settings = get_settings()
    crypto_mod.settings = config_mod.settings

    fake = _FakeProviderAuth()
    db = MagicMock()
    db.__getitem__.return_value = fake
    with patch("app.services.auth_service.get_database", return_value=db):
        yield fake

    get_settings.cache_clear()
    config_mod.settings = get_settings()
    crypto_mod.settings = config_mod.settings


def _stored_auth(collection: _FakeProviderAuth, provider: str) -> dict[str, Any]:
    doc = collection.find_one({"org_id": "org-1", "provider": provider})
    assert doc is not None
    return decrypt_json(doc["auth"])


def test_partial_update_keeps_untouched_secrets(collection):
    """bhashini has nine secrets and no catalog-required ones."""
    auth_service.upsert_provider_auth(
        "org-1",
        "bhashini",
        {"api_key": "key-one", "auth_token": "token-one", "function_id": "fn-one"},
    )
    auth_service.upsert_provider_auth("org-1", "bhashini", {"api_key": "key-two"})

    stored = _stored_auth(collection, "bhashini")
    assert stored == {
        "api_key": "key-two",
        "auth_token": "token-one",
        "function_id": "fn-one",
    }


def test_partial_update_still_enforces_required_fields(collection):
    """Merging must not let a required field be dropped — or smuggled past."""
    auth_service.upsert_provider_auth(
        "org-1",
        "aws_bedrock",
        {"aws_access_key": "AKIA-one", "aws_secret_key": "secret-one"},
    )
    auth_service.upsert_provider_auth("org-1", "aws_bedrock", {"aws_access_key": "AKIA-two"})

    stored = _stored_auth(collection, "aws_bedrock")
    assert stored == {"aws_access_key": "AKIA-two", "aws_secret_key": "secret-one"}


def test_create_rejects_a_missing_required_field(collection):
    with pytest.raises(ValueError):
        auth_service.upsert_provider_auth(
            "org-1",
            "aws_bedrock",
            {"aws_access_key": "AKIA-only"},
        )


def test_update_rejects_unknown_fields(collection):
    auth_service.upsert_provider_auth("org-1", "openai", {"api_key": "sk-one"})
    with pytest.raises(ValueError):
        auth_service.upsert_provider_auth("org-1", "openai", {"nope": "x"})
    assert _stored_auth(collection, "openai") == {"api_key": "sk-one"}


def test_update_response_is_masked(collection):
    auth_service.upsert_provider_auth("org-1", "openai", {"api_key": "sk-secret-key-1234"})
    response = auth_service.upsert_provider_auth(
        "org-1",
        "openai",
        {"api_key": "sk-replacement-5678"},
    )
    assert response["auth"]["api_key"].endswith("5678")
    assert response["auth"]["api_key"].startswith("*")


def test_undecryptable_blob_falls_back_to_replacement(collection):
    """A key rotation must not wedge the org out of re-entering credentials."""
    collection.insert_one(
        {
            "org_id": "org-1",
            "provider": "openai",
            "auth": "not-a-valid-fernet-token",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )
    auth_service.upsert_provider_auth("org-1", "openai", {"api_key": "sk-fresh"})
    assert _stored_auth(collection, "openai") == {"api_key": "sk-fresh"}


def test_stale_secret_names_are_dropped_on_merge(collection):
    """A field the catalog no longer lists must not fail the merged validation."""
    collection.insert_one(
        {
            "org_id": "org-1",
            "provider": "openai",
            "auth": encrypt_json({"api_key": "sk-one", "legacy_field": "stale"}),
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
        }
    )
    auth_service.upsert_provider_auth("org-1", "openai", {"api_key": "sk-two"})
    assert _stored_auth(collection, "openai") == {"api_key": "sk-two"}
