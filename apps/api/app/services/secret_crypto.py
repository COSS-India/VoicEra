"""Fernet helpers for encrypting ProviderAuth credential blobs at rest."""

from __future__ import annotations

import json
import logging
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

logger = logging.getLogger(__name__)

ENC_PREFIX = "enc:v1:"


class EncryptionNotConfiguredError(RuntimeError):
    """Raised when PROVIDER_AUTH_ENCRYPTION_KEY is missing or invalid."""


def _fernet() -> Fernet:
    key = (settings.PROVIDER_AUTH_ENCRYPTION_KEY or "").strip()
    if not key:
        raise EncryptionNotConfiguredError(
            "PROVIDER_AUTH_ENCRYPTION_KEY is not configured"
        )
    try:
        return Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    except Exception as exc:
        raise EncryptionNotConfiguredError(
            "PROVIDER_AUTH_ENCRYPTION_KEY is not a valid Fernet key"
        ) from exc


def encrypt_json(payload: dict[str, Any]) -> str:
    """Encrypt a JSON-serializable dict; return ``enc:v1:<token>``."""
    fernet = _fernet()
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    token = fernet.encrypt(raw).decode("utf-8")
    return f"{ENC_PREFIX}{token}"


def decrypt_json(value: str | dict[str, Any]) -> dict[str, Any]:
    """Decrypt an ``enc:v1:`` blob, or pass through a legacy plaintext dict."""
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise TypeError(f"Expected encrypted string or dict, got {type(value)!r}")

    if not value.startswith(ENC_PREFIX):
        # Legacy plaintext JSON string (unlikely) — try parse, else fail closed.
        try:
            parsed = json.loads(value)
            if isinstance(parsed, dict):
                logger.warning("Read legacy plaintext ProviderAuth JSON string")
                return parsed
        except json.JSONDecodeError:
            pass
        raise ValueError("ProviderAuth auth value is not encrypted")

    token = value[len(ENC_PREFIX) :].encode("utf-8")
    try:
        raw = _fernet().decrypt(token)
    except InvalidToken as exc:
        raise ValueError("Failed to decrypt ProviderAuth credentials") from exc
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("Decrypted ProviderAuth payload is not an object")
    return parsed
