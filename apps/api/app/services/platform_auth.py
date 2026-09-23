"""Platform-owned provider credentials used when an org has none of its own.

Sandbox deployments set ``PLATFORM_PROVIDER_AUTH`` so a brand-new organisation
can place a call without pasting an API key first. The credentials live in the
environment and are never written to the database: rotation is an env change,
there is nothing to migrate, and no tenant can read, overwrite or delete them.

Org-owned credentials always win — an organisation that brings its own key is
billed on its own account.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from app.config import settings
from app.services import auth_service
from app.services.provider_auth_catalog import validate_auth_payload

logger = logging.getLogger(__name__)

SOURCE_ORG = "org"
SOURCE_PLATFORM = "platform"


class PlatformAuthConfigError(ValueError):
    """Raised when ``PLATFORM_PROVIDER_AUTH`` cannot be parsed or validated."""


@lru_cache(maxsize=1)
def _credentials() -> dict[str, dict[str, Any]]:
    """Parse and validate the env blob once per process."""
    raw = (settings.PLATFORM_PROVIDER_AUTH or "").strip()
    if not raw:
        return {}

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PlatformAuthConfigError(
            f"PLATFORM_PROVIDER_AUTH is not valid JSON: {exc}"
        ) from exc

    if not isinstance(parsed, dict):
        raise PlatformAuthConfigError(
            "PLATFORM_PROVIDER_AUTH must be a JSON object keyed by provider id"
        )

    resolved: dict[str, dict[str, Any]] = {}
    for provider, auth in parsed.items():
        if not isinstance(auth, dict):
            raise PlatformAuthConfigError(
                f"PLATFORM_PROVIDER_AUTH[{provider!r}] must be an object of secret fields"
            )
        try:
            # Same validation an org admin's payload gets: unknown provider,
            # non-secret field or missing required secret all fail here.
            resolved[provider] = validate_auth_payload(provider, auth)
        except Exception as exc:
            raise PlatformAuthConfigError(
                f"PLATFORM_PROVIDER_AUTH[{provider!r}]: {exc}"
            ) from exc
    return resolved


def validate_config() -> None:
    """Fail startup on a malformed blob rather than the first call of the day."""
    _credentials.cache_clear()
    credentials = _credentials()
    if credentials:
        logger.info(
            "Platform provider credentials configured for: %s",
            ", ".join(sorted(credentials)),
        )


def providers() -> frozenset[str]:
    """Provider ids the platform supplies credentials for."""
    return frozenset(_credentials())


def resolve(org_id: str, provider: str) -> tuple[dict[str, Any], str] | None:
    """Return ``(auth, source)`` for ``provider``, or ``None`` if unavailable."""
    stored = auth_service.get_provider_auth(org_id, provider)
    if stored and stored.get("auth"):
        return stored["auth"], SOURCE_ORG

    platform = _credentials().get(provider)
    if platform:
        return dict(platform), SOURCE_PLATFORM
    return None
