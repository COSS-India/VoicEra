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
_cache_ids: frozenset[str] = frozenset()
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
    global _cache_ids, _cache_at
    _cache_ids = frozenset()
    _cache_at = 0.0


def is_authenticated(provider: str, configured: AbstractSet[str]) -> bool:
    """Return whether ``provider`` should show as authenticated."""
    gateway_id = LOCAL_GATEWAY_MODELS.get(provider)
    if gateway_id is not None:
        return gateway_id in _deployed_ids()
    return provider in configured


def _deployed_ids() -> frozenset[str]:
    global _cache_ids, _cache_at
    now = time.monotonic()
    if _cache_at and (now - _cache_at) < _CACHE_TTL_S:
        return _cache_ids
    _cache_ids = _fetch_deployed_ids()
    _cache_at = now
    return _cache_ids


def _fetch_deployed_ids() -> frozenset[str]:
    base = (os.getenv("MODEL_SERVER_URL") or "").strip().rstrip("/")
    if not base:
        return frozenset()
    url = f"{base}/models"
    try:
        with urllib.request.urlopen(url, timeout=2.0) as resp:
            payload = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return frozenset()
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return frozenset()
    ids: set[str] = set()
    for entry in data:
        if isinstance(entry, dict):
            model_id = entry.get("id")
            if isinstance(model_id, str) and model_id:
                ids.add(model_id)
    return frozenset(ids)
