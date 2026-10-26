"""Whether a provider is usable for configuration ``authenticated`` flags.

Cloud / adapter / telephony: org has stored credentials.
Local: model-server lists the provider's gateway model id.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import AbstractSet

# provider_id -> model-server slot id (GET /v1/models ``data[].id``).
LOCAL_GATEWAY_MODELS: dict[str, str] = {}

_CACHE_TTL_S = 10.0
_cache_entries: list[tuple[str, str, bool]] = []
_cache_at: float = 0.0


def register_local(provider: str, gateway_model_id: str) -> None:
    """Register a local provider's model-server slot id for readiness checks."""
    LOCAL_GATEWAY_MODELS[provider] = gateway_model_id


def clear_local_registrations() -> None:
    """Test helper: drop registered local providers."""
    LOCAL_GATEWAY_MODELS.clear()
    clear_deployed_cache()


def clear_deployed_cache() -> None:
    """Test helper: invalidate the deployed-models cache."""
    global _cache_entries, _cache_at
    _cache_entries = []
    _cache_at = 0.0


def deployed_llm_model_ids() -> frozenset[str]:
    """Model id(s) model-server currently has *deployed* in its ``llm`` slot
    (GET /models, 10s cache) — filtered by kind and deployed status, unlike
    _deployed_ids() below, which is used for provider readiness checks
    where any catalogued id (any kind, deployed or not) is an acceptable
    match. A caller that needs the actual callable LLM model name (e.g. to
    put in a chat-completion request's ``model`` field) needs this
    narrower, correctly-filtered view instead — the unfiltered set can
    otherwise just as easily yield an STT/TTS model id or an undeployed
    LLM catalogue entry."""
    return frozenset(
        entry_id for entry_id, kind, deployed in _cached_catalogue_entries() if kind == "llm" and deployed
    )


def is_authenticated(provider: str, configured: AbstractSet[str]) -> bool:
    """Return whether ``provider`` should show as authenticated."""
    gateway_id = LOCAL_GATEWAY_MODELS.get(provider)
    if gateway_id is not None:
        return gateway_id in _deployed_ids()
    return provider in configured


def _deployed_ids() -> frozenset[str]:
    return frozenset(entry_id for entry_id, _kind, _deployed in _cached_catalogue_entries())


def _cached_catalogue_entries() -> list[tuple[str, str, bool]]:
    global _cache_entries, _cache_at
    now = time.monotonic()
    if _cache_at and (now - _cache_at) < _CACHE_TTL_S:
        return _cache_entries
    _cache_entries = _fetch_catalogue_entries()
    _cache_at = now
    return _cache_entries


def _fetch_catalogue_entries() -> list[tuple[str, str, bool]]:
    """Raw (id, kind, deployed) tuples from model-server's GET /models —
    the full catalogue (every model of every kind model-server can host,
    not just what's currently deployed)."""
    base = (os.getenv("MODEL_SERVER_URL") or "").strip().rstrip("/")
    if not base:
        return []
    url = f"{base}/models"
    try:
        with urllib.request.urlopen(url, timeout=2.0) as resp:
            payload = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return []
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return []
    entries: list[tuple[str, str, bool]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")
        if isinstance(entry_id, str) and entry_id:
            entries.append((entry_id, str(entry.get("kind") or ""), bool(entry.get("deployed"))))
    return entries
