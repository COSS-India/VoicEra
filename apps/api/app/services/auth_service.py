"""Persist and retrieve org-scoped provider auth credentials."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.database import get_database
from app.services.provider_auth_catalog import (
    provider_auth_catalog,
    validate_auth_payload,
)
from app.services.secret_crypto import decrypt_json, encrypt_json
from app.utils.mongo_utils import prepare_mongo_response

logger = logging.getLogger(__name__)

COLLECTION = "ProviderAuth"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask_secret_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_mask_secret_value(item) for item in value]
    if not isinstance(value, str):
        return "****"
    key = value.strip()
    if len(key) <= 4:
        return "****"
    return f"{'*' * (len(key) - 4)}{key[-4:]}"


def mask_auth_secrets(provider: str, auth: dict[str, Any]) -> dict[str, Any]:
    """Mask secret fields (all stored fields are secrets)."""
    try:
        catalog = provider_auth_catalog(provider)
        secrets = set(catalog.get("secrets", [])) or set(auth)
    except Exception:
        secrets = set(auth)
    out: dict[str, Any] = {}
    for key, value in auth.items():
        out[key] = _mask_secret_value(value) if key in secrets else value
    return out


def _decode_auth(stored: Any) -> dict[str, Any]:
    if stored is None:
        return {}
    return decrypt_json(stored)


def _to_response(
    doc: dict[str, Any],
    *,
    mask_secrets: bool,
) -> dict[str, Any]:
    prepared = prepare_mongo_response(doc) or {}
    prepared.pop("_id", None)
    auth = _decode_auth(prepared.get("auth"))
    if mask_secrets:
        auth = mask_auth_secrets(str(prepared.get("provider", "")), auth)
    return {
        "org_id": prepared.get("org_id"),
        "provider": prepared.get("provider"),
        "auth": auth,
        "created_at": prepared.get("created_at"),
        "updated_at": prepared.get("updated_at"),
    }


def upsert_provider_auth(
    org_id: str,
    provider: str,
    auth: dict[str, Any],
) -> dict[str, Any]:
    """Create or update encrypted auth for ``provider`` in ``org_id``."""
    validated = validate_auth_payload(provider, auth)
    encrypted = encrypt_json(validated)
    db = get_database()
    collection = db[COLLECTION]
    now = _now_iso()

    existing = collection.find_one({"org_id": org_id, "provider": provider})
    if existing:
        collection.update_one(
            {"org_id": org_id, "provider": provider},
            {"$set": {"auth": encrypted, "updated_at": now}},
        )
        logger.info("Provider auth updated org=%s provider=%s", org_id, provider)
        doc = collection.find_one({"org_id": org_id, "provider": provider})
        assert doc is not None
        return _to_response(doc, mask_secrets=False)

    doc = {
        "org_id": org_id,
        "provider": provider,
        "auth": encrypted,
        "created_at": now,
        "updated_at": now,
    }
    collection.insert_one(doc)
    logger.info("Provider auth created org=%s provider=%s", org_id, provider)
    # Return decrypted view (do not echo ciphertext to clients).
    return {
        "org_id": org_id,
        "provider": provider,
        "auth": validated,
        "created_at": now,
        "updated_at": now,
    }


def get_provider_auth(
    org_id: str,
    provider: str,
    *,
    mask_secrets: bool = False,
) -> dict[str, Any] | None:
    """Fetch stored auth for one provider, or ``None`` if missing."""
    db = get_database()
    doc = db[COLLECTION].find_one({"org_id": org_id, "provider": provider})
    if not doc:
        return None
    return _to_response(doc, mask_secrets=mask_secrets)


def list_configured_providers(org_id: str) -> list[str]:
    """Provider ids that have stored auth for the organisation."""
    db = get_database()
    providers = db[COLLECTION].distinct("provider", {"org_id": org_id})
    return sorted(str(p) for p in providers)


def list_provider_auth_for_org(org_id: str) -> list[dict[str, Any]]:
    """All decrypted provider credentials for ``org_id`` (bot / unmasked)."""
    db = get_database()
    docs = list(db[COLLECTION].find({"org_id": org_id}))
    results = [_to_response(doc, mask_secrets=False) for doc in docs]
    results.sort(key=lambda item: str(item.get("provider") or ""))
    return results


def delete_provider_auth(org_id: str, provider: str) -> bool:
    """Delete stored auth. Returns ``True`` when a document was removed."""
    db = get_database()
    result = db[COLLECTION].delete_one({"org_id": org_id, "provider": provider})
    if result.deleted_count:
        logger.info("Provider auth deleted org=%s provider=%s", org_id, provider)
        return True
    return False
