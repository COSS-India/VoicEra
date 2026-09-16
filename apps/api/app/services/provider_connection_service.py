"""Org-scoped named endpoints for connection-based providers.

``ProviderAuth`` holds one credential row per provider per organisation, which
is right for a vendor with one fixed host. A provider whose endpoint the
operator supplies needs the opposite: several rows, each with its own URL and
its own key. Those live here, in ``ProviderConnections``, and an agent stores
only the ``connection_id``. The key is Fernet-encrypted with the same
``PROVIDER_AUTH_ENCRYPTION_KEY`` as every other stored secret.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import socket
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx
from pymongo.errors import DuplicateKeyError

from app.config import settings
from app.database import get_database
from app.services.secret_crypto import decrypt_json, encrypt_json
from app.utils.mongo_utils import prepare_mongo_response
from apps.providers.base import CONNECTION_PROVIDERS

logger = logging.getLogger(__name__)

COLLECTION = "ProviderConnections"

# Only LLM endpoints today. The field is stored so an OpenAI-compatible STT or
# TTS lands as a row here rather than as a second collection.
KIND = "llm"

_URL_SCHEMES = ("http://", "https://")
_SLUG_STRIP = re.compile(r"[^a-z0-9]+")

# Paths a user may paste from vendor docs; the base URL sits above them.
_OPERATION_SUFFIXES = ("/chat/completions", "/completions", "/responses")

# Cloud instance-metadata addresses. The link-local range covers 169.254.169.254
# (AWS, GCP, Azure) however it is spelled; AWS also serves metadata over the
# unique-local address below, which is not link-local. Everything else private
# stays reachable on purpose — a self-hosted vLLM on the LAN is the main thing
# this feature serves.
_BLOCKED_IPS = frozenset({ipaddress.ip_address("fd00:ec2::254")})


class ProviderConnectionError(ValueError):
    """Raised when a connection payload is unusable."""


class ProviderConnectionNotFoundError(Exception):
    """Raised when a connection is missing for the organisation."""

    def __init__(self, connection_id: str) -> None:
        self.connection_id = connection_id
        super().__init__(f"Provider connection not found: {connection_id}")


class ProviderConnectionConflictError(Exception):
    """Raised when a connection name is already taken in the organisation."""

    def __init__(self, name: str) -> None:
        self.name = name
        super().__init__(f"Provider connection name already exists: {name}")


class ProviderConnectionInUseError(Exception):
    """Raised when deleting a connection that agents still reference."""

    def __init__(self, connection_id: str, agent_names: list[str]) -> None:
        self.connection_id = connection_id
        self.agent_names = agent_names
        super().__init__(
            "Provider connection is in use by: " + ", ".join(agent_names)
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify(name: str) -> str:
    slug = _SLUG_STRIP.sub("-", name.strip().lower()).strip("-")
    return slug or uuid.uuid4().hex[:8]


def _mask(value: Any) -> Any:
    if isinstance(value, list):
        return [_mask(item) for item in value]
    text = str(value or "").strip()
    if len(text) <= 4:
        return "****"
    return f"{'*' * (len(text) - 4)}{text[-4:]}"


def validate_provider(provider: str) -> str:
    """Reject providers that are not connection-based."""
    normalized = (provider or "").strip()
    if normalized not in CONNECTION_PROVIDERS:
        raise ProviderConnectionError(
            f"Provider {normalized!r} does not use connections; "
            f"store its credentials with POST /auth instead "
            f"(connection-based: {', '.join(sorted(CONNECTION_PROVIDERS))})"
        )
    return normalized


def normalise_base_url(base_url: str) -> str:
    """Trim the URL and reject anything the probe must not be pointed at.

    A saved endpoint is fetched server-side by ``probe_endpoint``, so the host
    is checked here rather than at call time: link-local metadata services are
    refused, and an optional allowlist narrows it further for shared installs.
    """
    url = (base_url or "").strip().rstrip("/")
    if not url:
        raise ProviderConnectionError("base_url is required")
    if not url.startswith(_URL_SCHEMES):
        raise ProviderConnectionError("base_url must start with http:// or https://")

    # The OpenAI client appends the operation itself, so a base ending in one is
    # always wrong — and pasting the full completions URL from a vendor's docs
    # is the most common way to get here. Trim it rather than fail on it.
    for suffix in _OPERATION_SUFFIXES:
        if url.endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")
            break

    host = (urlsplit(url).hostname or "").strip()
    if not host:
        raise ProviderConnectionError("base_url has no host")

    allowed = [
        entry.strip().lower()
        for entry in (settings.PROVIDER_CONNECTION_ALLOWED_HOSTS or "").split(",")
        if entry.strip()
    ]
    if allowed and host.lower() not in allowed:
        raise ProviderConnectionError(
            f"Host {host!r} is not in PROVIDER_CONNECTION_ALLOWED_HOSTS"
        )

    for address in _resolved_ips(host):
        if address.is_link_local or address in _BLOCKED_IPS:
            raise ProviderConnectionError(
                f"base_url resolves to a blocked address: {address}"
            )
    return url


def _parse_ip(raw: str) -> Any | None:
    """Parse to a comparable address, or ``None`` when it is not one.

    An IPv4-mapped IPv6 address such as ``::ffff:169.254.169.254`` routes to the
    IPv4 address it wraps, so it has to be compared as that address rather than
    by its own text form. A scope id (``fe80::1%eth0``) is dropped first.
    """
    try:
        address = ipaddress.ip_address(raw.split("%", 1)[0])
    except ValueError:
        return None
    return getattr(address, "ipv4_mapped", None) or address


def _resolved_ips(host: str) -> list[Any]:
    """Literal IP, or every A/AAAA record. DNS failure is left to the probe."""
    literal = _parse_ip(host)
    if literal is not None:
        return [literal]
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return []
    resolved = (_parse_ip(str(info[4][0])) for info in infos)
    return [address for address in resolved if address is not None]


def _first_key(api_key: str | list[str] | None) -> str:
    if isinstance(api_key, list):
        return str(api_key[0]) if api_key else ""
    return str(api_key or "")


def _validate_key(api_key: str | list[str]) -> str | list[str]:
    if isinstance(api_key, list):
        keys = [str(k).strip() for k in api_key if str(k).strip()]
        if not keys:
            raise ProviderConnectionError("api_key list is empty")
        return keys
    key = str(api_key or "").strip()
    if not key:
        raise ProviderConnectionError("api_key is required")
    return key


def _to_response(doc: dict[str, Any], *, mask_secrets: bool) -> dict[str, Any]:
    prepared = prepare_mongo_response(doc) or {}
    prepared.pop("_id", None)
    stored = prepared.pop("secret", None)
    api_key = decrypt_json(stored).get("api_key", "") if stored else ""
    prepared["api_key"] = _mask(api_key) if mask_secrets else api_key
    return prepared


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def create_connection(
    org_id: str,
    payload: dict[str, Any],
    *,
    created_by: str | None = None,
) -> dict[str, Any]:
    """Store a new endpoint. Name must be unique within the organisation."""
    provider = validate_provider(payload.get("provider") or "openai_compatible")
    name = str(payload.get("name") or "").strip()
    if not name:
        raise ProviderConnectionError("name is required")

    base_url = normalise_base_url(str(payload.get("base_url") or ""))
    api_key = _validate_key(payload.get("api_key"))
    models = [str(m).strip() for m in (payload.get("models") or []) if str(m).strip()]
    default_model = (payload.get("default_model") or "").strip() or None
    if default_model and models and default_model not in models:
        models.append(default_model)

    now = _now_iso()
    doc = {
        "id": uuid.uuid4().hex,
        "org_id": org_id,
        "kind": KIND,
        "provider": provider,
        "name": name,
        "slug": _slugify(name),
        "base_url": base_url,
        "secret": encrypt_json({"api_key": api_key}),
        "models": models,
        "default_model": default_model,
        "supports_tools": bool(payload.get("supports_tools", False)),
        "enabled": bool(payload.get("enabled", True)),
        "verified_at": None,
        "created_at": now,
        "created_by": created_by,
        "updated_at": now,
    }

    try:
        get_database()[COLLECTION].insert_one(dict(doc))
    except DuplicateKeyError as exc:
        raise ProviderConnectionConflictError(name) from exc

    logger.info(
        "Provider connection created org=%s provider=%s id=%s", org_id, provider, doc["id"]
    )
    return _to_response(doc, mask_secrets=True)


def list_connections(
    org_id: str,
    *,
    provider: str | None = None,
    enabled_only: bool = False,
) -> list[dict[str, Any]]:
    """Connections for the organisation, keys masked."""
    query: dict[str, Any] = {"org_id": org_id}
    if provider:
        query["provider"] = provider
    if enabled_only:
        query["enabled"] = True
    docs = list(get_database()[COLLECTION].find(query))
    results = [_to_response(doc, mask_secrets=True) for doc in docs]
    results.sort(key=lambda item: str(item.get("name") or "").lower())
    return results


def get_connection(
    org_id: str,
    connection_id: str,
    *,
    mask_secrets: bool = True,
) -> dict[str, Any]:
    """One connection, or raise ``ProviderConnectionNotFoundError``."""
    doc = get_database()[COLLECTION].find_one({"org_id": org_id, "id": connection_id})
    if not doc:
        raise ProviderConnectionNotFoundError(connection_id)
    return _to_response(doc, mask_secrets=mask_secrets)


def update_connection(
    org_id: str,
    connection_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Patch stored fields. Only keys present in ``payload`` are written."""
    collection = get_database()[COLLECTION]
    existing = collection.find_one({"org_id": org_id, "id": connection_id})
    if not existing:
        raise ProviderConnectionNotFoundError(connection_id)

    updates: dict[str, Any] = {}
    if "name" in payload and payload["name"] is not None:
        name = str(payload["name"]).strip()
        if not name:
            raise ProviderConnectionError("name must not be empty")
        updates["name"] = name
        updates["slug"] = _slugify(name)
    if "base_url" in payload and payload["base_url"] is not None:
        updates["base_url"] = normalise_base_url(str(payload["base_url"]))
        # The endpoint moved; the old probe result no longer describes it.
        updates["verified_at"] = None
    if "api_key" in payload and payload["api_key"] is not None:
        updates["secret"] = encrypt_json({"api_key": _validate_key(payload["api_key"])})
    if "models" in payload and payload["models"] is not None:
        updates["models"] = [
            str(m).strip() for m in payload["models"] if str(m).strip()
        ]
    if "default_model" in payload:
        updates["default_model"] = (payload["default_model"] or "").strip() or None
    if "supports_tools" in payload and payload["supports_tools"] is not None:
        updates["supports_tools"] = bool(payload["supports_tools"])
    if "enabled" in payload and payload["enabled"] is not None:
        updates["enabled"] = bool(payload["enabled"])

    if not updates:
        return _to_response(existing, mask_secrets=True)

    updates["updated_at"] = _now_iso()
    try:
        collection.update_one(
            {"org_id": org_id, "id": connection_id}, {"$set": updates}
        )
    except DuplicateKeyError as exc:
        raise ProviderConnectionConflictError(str(updates.get("name") or "")) from exc

    doc = collection.find_one({"org_id": org_id, "id": connection_id})
    assert doc is not None
    logger.info("Provider connection updated org=%s id=%s", org_id, connection_id)
    return _to_response(doc, mask_secrets=True)


def delete_connection(org_id: str, connection_id: str) -> bool:
    """Delete a connection unless an agent still points at it."""
    referencing = agents_using(org_id, connection_id)
    if referencing:
        raise ProviderConnectionInUseError(connection_id, referencing)

    result = get_database()[COLLECTION].delete_one(
        {"org_id": org_id, "id": connection_id}
    )
    if result.deleted_count:
        logger.info("Provider connection deleted org=%s id=%s", org_id, connection_id)
        return True
    return False


def agents_using(org_id: str, connection_id: str) -> list[str]:
    """Names of agents whose llm_config references ``connection_id``."""
    docs = get_database()["Agents"].find(
        {"org_id": org_id, "config.models.llm_config.connection_id": connection_id},
        {"name": 1},
    )
    return sorted(str(doc.get("name") or doc.get("agent_id") or "?") for doc in docs)


# ---------------------------------------------------------------------------
# Lookups used elsewhere in the API
# ---------------------------------------------------------------------------


def connection_exists(org_id: str, connection_id: str, *, provider: str) -> bool:
    """Whether an enabled connection with this id serves ``provider``."""
    return bool(
        get_database()[COLLECTION].find_one(
            {
                "org_id": org_id,
                "id": connection_id,
                "provider": provider,
                "enabled": True,
            },
            {"id": 1},
        )
    )


def supports_tools(org_id: str, connection_id: str) -> bool:
    """Whether the endpoint was marked as implementing tool calling."""
    doc = get_database()[COLLECTION].find_one(
        {"org_id": org_id, "id": connection_id}, {"supports_tools": 1}
    )
    return bool((doc or {}).get("supports_tools"))


def configured_providers(org_id: str) -> list[str]:
    """Connection-based provider ids with at least one enabled endpoint."""
    providers = get_database()[COLLECTION].distinct(
        "provider", {"org_id": org_id, "enabled": True}
    )
    return sorted(str(p) for p in providers)


def resolve_auth(org_id: str, connection_id: str) -> dict[str, Any]:
    """Decrypted ``{base_url, api_key}`` for the runtime to merge into a config."""
    stored = get_connection(org_id, connection_id, mask_secrets=False)
    if not stored.get("enabled", True):
        raise ProviderConnectionError(
            f"Provider connection is disabled: {connection_id}"
        )
    return {"base_url": stored["base_url"], "api_key": stored["api_key"]}


# ---------------------------------------------------------------------------
# Reachability probe
# ---------------------------------------------------------------------------


def _get(url: str, headers: dict[str, str]) -> Any:
    return httpx.get(
        url,
        headers=headers,
        timeout=settings.PROVIDER_CONNECTION_PROBE_TIMEOUT,
        follow_redirects=False,
    )


def _redirect_error(response: Any) -> str:
    return (
        f"Endpoint redirected to {response.headers.get('location', 'elsewhere')!r}; "
        "redirects are not followed. Use the final URL."
    )


def _list_models(url: str, headers: dict[str, str]) -> tuple[list[str] | None, str | None]:
    """Model ids from ``GET /models``, or ``(None, reason)`` when it is absent.

    ``/models`` is part of the OpenAI spec but plenty of compatible servers
    only implement ``/chat/completions`` — a missing list is not a failure.
    """
    try:
        response = _get(f"{url}/models", headers)
    except httpx.HTTPError as exc:
        return None, f"Request failed: {exc}"

    if 300 <= response.status_code < 400:
        return None, _redirect_error(response)
    if response.status_code >= 400:
        return None, f"GET /models returned {response.status_code}"

    try:
        payload = response.json()
    except ValueError:
        return None, "GET /models did not return JSON"

    entries = payload.get("data") if isinstance(payload, dict) else None
    ids = [
        str(entry.get("id"))
        for entry in (entries or [])
        if isinstance(entry, dict) and entry.get("id")
    ]
    return sorted(ids), None


def _probe_chat(
    url: str,
    headers: dict[str, str],
    model: str | None,
) -> dict[str, Any]:
    """Confirm an endpoint by asking ``/chat/completions`` for one token.

    Status alone answers the question the operator has: is this URL an
    OpenAI-shaped API, and does my key work? A rejected request body still
    proves both, so it is reported as reachable with the server's complaint.
    """
    body = {
        "model": model or "",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    try:
        response = httpx.post(
            f"{url}/chat/completions",
            headers={**headers, "Content-Type": "application/json"},
            json=body,
            timeout=settings.PROVIDER_CONNECTION_PROBE_TIMEOUT,
            follow_redirects=False,
        )
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"Request failed: {exc}"}

    status = response.status_code
    if 300 <= status < 400:
        return {"ok": False, "error": _redirect_error(response)}
    if status in (401, 403):
        return {"ok": False, "error": f"Endpoint rejected the API key ({status})."}
    if status == 404:
        return {
            "ok": False,
            "error": (
                "No /models and no /chat/completions under this base URL. "
                "Give the root the endpoint documents, e.g. "
                "http://host:8080/v1 — not the full completions path."
            ),
        }
    if status < 300:
        return {"ok": True, "note": "Reachable — completed a one-token request."}
    # 4xx/5xx from here on: the server parsed an OpenAI-shaped request and
    # answered on its own terms, which is enough to confirm the URL and key.
    return {
        "ok": True,
        "note": (
            f"Reachable, but the test request was rejected ({status}): "
            f"{response.text[:200]}"
        ),
    }


def probe_endpoint(
    base_url: str,
    api_key: str | list[str] | None,
    model: str | None = None,
) -> dict[str, Any]:
    """Check an endpoint and list its models. Never raises for a failure.

    ``GET /models`` is tried first because it is the only way to populate the
    agent's model picker. When the endpoint does not serve it, the check falls
    back to ``/chat/completions`` so an endpoint that implements only the one
    required operation still verifies — the model ids are then typed by hand.

    Redirects are not followed: one would move the request to a host that never
    passed ``normalise_base_url``.
    """
    try:
        url = normalise_base_url(base_url)
    except ProviderConnectionError as exc:
        return {"ok": False, "models": [], "error": str(exc)}

    key = _first_key(api_key)
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    started = time.monotonic()

    models, reason = _list_models(url, headers)
    if models:
        return {
            "ok": True,
            "models": models,
            "latency_ms": int((time.monotonic() - started) * 1000),
        }

    fallback = _probe_chat(url, headers, model)
    latency_ms = int((time.monotonic() - started) * 1000)
    if not fallback["ok"]:
        return {
            "ok": False,
            "models": [],
            "latency_ms": latency_ms,
            "error": fallback["error"],
        }

    note = fallback.get("note", "")
    if reason:
        note = f"{note} This endpoint publishes no model list ({reason}), so enter model ids yourself."
    elif models is not None:
        note = f"{note} This endpoint's model list is empty, so enter model ids yourself."
    return {"ok": True, "models": [], "latency_ms": latency_ms, "note": note.strip()}


def probe_and_record(org_id: str, connection_id: str) -> dict[str, Any]:
    """Probe a stored connection; on success cache its model list."""
    stored = get_connection(org_id, connection_id, mask_secrets=False)
    # The stored model is what the chat fallback asks for when the endpoint
    # publishes no list — without it that request is rejected for a missing model.
    fallback_model = stored.get("default_model") or next(
        iter(stored.get("models") or []), None
    )
    result = probe_endpoint(
        stored["base_url"], stored["api_key"], model=fallback_model
    )
    if result.get("ok"):
        updates: dict[str, Any] = {"verified_at": _now_iso()}
        if result["models"]:
            updates["models"] = result["models"]
        get_database()[COLLECTION].update_one(
            {"org_id": org_id, "id": connection_id}, {"$set": updates}
        )
    return result
