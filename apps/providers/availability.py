"""Whether a provider is usable for configuration ``authenticated`` flags.

Cloud / adapter / telephony: org has stored credentials, or the platform
supplies them on the org's behalf.
Local: always usable — the deployment ships the model-server, so these need no
credential and are offered to every organisation for free.
"""

from __future__ import annotations

from typing import AbstractSet

# provider_id -> model-server slot id (GET /v1/models ``data[].id``).
LOCAL_GATEWAY_MODELS: dict[str, str] = {}


def register_local(provider: str, gateway_model_id: str) -> None:
    """Mark a provider as served by the model-server, under this slot id."""
    LOCAL_GATEWAY_MODELS[provider] = gateway_model_id


def clear_local_registrations() -> None:
    """Test helper: drop registered local providers."""
    LOCAL_GATEWAY_MODELS.clear()


def is_authenticated(
    provider: str,
    configured: AbstractSet[str],
    platform: AbstractSet[str] = frozenset(),
) -> bool:
    """Return whether ``provider`` should show as authenticated (selectable)."""
    return auth_source(provider, configured, platform) is not None


def auth_source(
    provider: str,
    configured: AbstractSet[str],
    platform: AbstractSet[str] = frozenset(),
) -> str | None:
    """Why ``provider`` is usable: ``"local"``, ``"org"``, ``"platform"``, or None.

    Local first (needs no credential at all), then the org's own credentials,
    then the platform's — an org that connected its own key should read as
    "Connected", not "Included".

    Local providers are assumed deployed rather than probed: they are part of
    the deployment, so a momentarily unreachable model-server must not make
    them vanish from the UI.
    """
    if provider in LOCAL_GATEWAY_MODELS:
        return "local"
    if provider in configured:
        return "org"
    if provider in platform:
        return "platform"
    return None
