"""Platform-owned provider credentials, used when an organisation has none.

Set ``PLATFORM_PROVIDER_AUTH`` to a JSON object keyed by provider id, e.g.
``{"openai": {"api_key": "sk-..."}}``, and every organisation -- including one
created by a brand-new signup -- can use that provider without pasting a key.
This is what sandbox.voicera.world does (branch ``dev-sandbox-v2``,
``app/services/platform_auth.py``); this is the same contract, kept small:

* **Env only, never the database.** Rotation is an env change and a restart;
  no tenant can read, overwrite or delete the platform key.
* **The organisation's own key always wins.** An org that connects a provider
  itself uses -- and pays for -- its own account.
* **Plaintext only for the voice runtime.** ``GET /auth/{provider}`` returns
  secrets unmasked to admins, and every signup is a super_admin, so a platform
  key returned there would be readable by anyone who can sign up. Users get it
  masked; only the runtime's bot token (``bot@voicera.internal``, minted with
  ``INTERNAL_API_KEY``) gets the value.
* **No telephony.** A platform telephony key would let any signup provision
  applications and numbers on the platform's account, so it is refused at
  startup rather than ignored.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from app.config import settings
from app.services.provider_auth_catalog import validate_auth_payload

logger = logging.getLogger(__name__)

#: The subject of the runtime's service JWT (``routers/users.py``).
BOT_SERVICE_EMAIL = "bot@voicera.internal"


class PlatformAuthConfigError(ValueError):
    """``PLATFORM_PROVIDER_AUTH`` cannot be parsed or validated."""


def _is_telephony(provider: str) -> bool:
    from apps.telephony.schema import provider_level_auth

    return provider_level_auth(provider) is not None


@lru_cache(maxsize=1)
def _credentials() -> dict[str, dict[str, Any]]:
    raw = (settings.PLATFORM_PROVIDER_AUTH or "").strip()
    # Tolerate a value quoted in .env; Compose and pydantic disagree on quotes.
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
        raw = raw[1:-1].strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PlatformAuthConfigError(f"PLATFORM_PROVIDER_AUTH is not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise PlatformAuthConfigError("PLATFORM_PROVIDER_AUTH must be a JSON object keyed by provider id")

    resolved: dict[str, dict[str, Any]] = {}
    for provider, auth in parsed.items():
        if not isinstance(auth, dict):
            raise PlatformAuthConfigError(f"PLATFORM_PROVIDER_AUTH[{provider!r}] must be an object")
        if _is_telephony(provider):
            raise PlatformAuthConfigError(
                f"PLATFORM_PROVIDER_AUTH[{provider!r}]: telephony providers cannot be supplied "
                "by the platform -- each organisation must connect its own"
            )
        try:
            resolved[provider] = validate_auth_payload(provider, auth)
        except Exception as exc:
            raise PlatformAuthConfigError(f"PLATFORM_PROVIDER_AUTH[{provider!r}]: {exc}") from exc
    return resolved


def validate_config() -> None:
    """Fail at startup on a malformed value, not on the first call of the day."""
    _credentials.cache_clear()
    names = sorted(_credentials())
    if names:
        logger.info("Platform provider credentials configured for: %s", ", ".join(names))


def providers() -> frozenset[str]:
    """Provider ids the platform supplies credentials for."""
    return frozenset(_credentials())


def get(provider: str) -> dict[str, Any] | None:
    """The platform's credentials for ``provider`` (a copy), or None."""
    auth = _credentials().get(provider)
    return dict(auth) if auth else None


def is_runtime(current_user: dict[str, Any]) -> bool:
    """True for the voice runtime's service token, the only plaintext reader."""
    return current_user.get("email") == BOT_SERVICE_EMAIL
