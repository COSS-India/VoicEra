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


def _merge_with_stored(
    provider: str,
    stored: Any,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """Overlay ``incoming`` on the stored secrets, keeping omitted fields.

    Clients never see stored secrets (they are masked), so they cannot resend
    the fields they did not change. Without this merge, updating one field of a
    multi-secret provider — bhashini has nine, none of them catalog-required —
    would silently drop the rest on the ``$set``.
    """
    try:
        current = decrypt_json(stored)
    except Exception:
        logger.warning(
            "Could not decrypt existing auth for provider=%s; replacing it wholesale",
            provider,
        )
        return dict(incoming)

    if not isinstance(current, dict):
        return dict(incoming)

    # Drop anything the catalog no longer treats as a secret, or validation of
    # the merged payload would reject a field this org never sent.
    secrets = set(provider_auth_catalog(provider).get("secrets", []))
    kept = {key: value for key, value in current.items() if key in secrets}
    return {**kept, **incoming}


def upsert_provider_auth(
    org_id: str,
    provider: str,
    auth: dict[str, Any],
) -> dict[str, Any]:
    """Create or update encrypted auth for ``provider`` in ``org_id``.

    Fields omitted from ``auth`` keep their stored value; use
    ``DELETE /auth/{provider}`` to clear credentials entirely.
    """
    db = get_database()
    collection = db[COLLECTION]
    now = _now_iso()

    existing = collection.find_one({"org_id": org_id, "provider": provider})
    if existing:
        # Validate the merged result so catalog-required fields stay enforced.
        validated = validate_auth_payload(
            provider,
            _merge_with_stored(provider, existing.get("auth"), auth),
        )
        encrypted = encrypt_json(validated)
        collection.update_one(
            {"org_id": org_id, "provider": provider},
            {"$set": {"auth": encrypted, "updated_at": now}},
        )
        logger.info("Provider auth updated org=%s provider=%s", org_id, provider)
        doc = collection.find_one({"org_id": org_id, "provider": provider})
        assert doc is not None
        return _to_response(doc, mask_secrets=True)

    validated = validate_auth_payload(provider, auth)
    encrypted = encrypt_json(validated)
    doc = {
        "org_id": org_id,
        "provider": provider,
        "auth": encrypted,
        "created_at": now,
        "updated_at": now,
    }
    collection.insert_one(doc)
    logger.info("Provider auth created org=%s provider=%s", org_id, provider)
    # Masked view: never echo ciphertext, and never echo the key just stored.
    return {
        "org_id": org_id,
        "provider": provider,
        "auth": mask_auth_secrets(provider, validated),
        "created_at": now,
        "updated_at": now,
    }


def get_provider_auth(org_id: str, provider: str) -> dict[str, Any] | None:
    """Decrypted stored auth, or ``None`` if missing.

    Internal callers only. Never return this from a user-facing route — use
    :func:`get_provider_auth_masked`.
    """
    db = get_database()
    doc = db[COLLECTION].find_one({"org_id": org_id, "provider": provider})
    if not doc:
        return None
    return _to_response(doc, mask_secrets=False)


def get_provider_auth_masked(org_id: str, provider: str) -> dict[str, Any] | None:
    """Stored auth with every secret masked — the only form a client may see."""
    db = get_database()
    doc = db[COLLECTION].find_one({"org_id": org_id, "provider": provider})
    if not doc:
        return None
    return _to_response(doc, mask_secrets=True)


def list_configured_providers(org_id: str) -> list[str]:
    """Provider ids that have stored auth for the organisation."""
    db = get_database()
    providers = db[COLLECTION].distinct("provider", {"org_id": org_id})
    return sorted(str(p) for p in providers)


def delete_provider_auth(org_id: str, provider: str) -> bool:
    """Delete stored auth. Returns ``True`` when a document was removed."""
    db = get_database()
    result = db[COLLECTION].delete_one({"org_id": org_id, "provider": provider})
    if result.deleted_count:
        logger.info("Provider auth deleted org=%s provider=%s", org_id, provider)
        return True
    return False
