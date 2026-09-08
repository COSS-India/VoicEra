"""Unit tests for ProviderAuth Fernet encryption."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.config import get_settings
from app.services.secret_crypto import (
    ENC_PREFIX,
    EncryptionNotConfiguredError,
    decrypt_json,
    encrypt_json,
)


@pytest.fixture(autouse=True)
def _fernet_key(monkeypatch: pytest.MonkeyPatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("PROVIDER_AUTH_ENCRYPTION_KEY", key)
    get_settings.cache_clear()
    # Re-bind settings used by secret_crypto
    import app.config as config_mod
    import app.services.secret_crypto as crypto_mod

    config_mod.settings = get_settings()
    crypto_mod.settings = config_mod.settings
    yield
    get_settings.cache_clear()
    config_mod.settings = get_settings()
    crypto_mod.settings = config_mod.settings


def test_encrypt_decrypt_round_trip():
    payload = {"api_key": "sk-test-1234", "auth_token": "tok"}
    blob = encrypt_json(payload)
    assert blob.startswith(ENC_PREFIX)
    assert decrypt_json(blob) == payload


def test_encrypt_requires_key(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PROVIDER_AUTH_ENCRYPTION_KEY", "")
    get_settings.cache_clear()
    import app.config as config_mod
    import app.services.secret_crypto as crypto_mod

    config_mod.settings = get_settings()
    crypto_mod.settings = config_mod.settings
    with pytest.raises(EncryptionNotConfiguredError):
        encrypt_json({"api_key": "x"})


def test_legacy_plaintext_dict_passthrough():
    assert decrypt_json({"api_key": "plain"}) == {"api_key": "plain"}


def test_validate_secrets_only_rejects_non_secret():
    from app.services.provider_auth_catalog import validate_auth_payload

    with pytest.raises(ValueError, match="rejected project_id"):
        validate_auth_payload(
            "google",
            {
                "api_key": "ai-studio-key",
                "credentials": '{"type":"service_account"}',
                "project_id": "my-project",
            },
        )

    cleaned = validate_auth_payload(
        "google",
        {
            "api_key": "ai-studio-key",
            "credentials": '{"type":"service_account"}',
        },
    )
    assert set(cleaned) == {"api_key", "credentials"}
