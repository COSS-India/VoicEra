"""Provider-level auth catalogs (STT / TTS / LLM / telephony merged by provider id)."""

from __future__ import annotations

from typing import Any

from apps.providers.schema import (
    all_provider_level_auth as providers_all_level_auth,
    provider_level_auth as providers_level_auth,
)
from apps.telephony.schema import (
    all_provider_level_auth as telephony_all_level_auth,
    provider_level_auth as telephony_level_auth,
)


class UnknownAuthProviderError(KeyError):
    """Raised when a provider id is not registered for any kind."""

    def __init__(self, provider: str) -> None:
        self.provider = provider
        super().__init__(provider)

    def __str__(self) -> str:
        return f"Unknown provider: {self.provider}"


def provider_auth_catalog(provider: str) -> dict[str, Any]:
    """Auth catalog for ``provider`` across media + telephony registries."""
    media = providers_level_auth(provider)
    telephony = telephony_level_auth(provider)
    if media is None and telephony is None:
        raise UnknownAuthProviderError(provider)
    if media is not None and telephony is not None:
        # No overlapping ids today; if that changes, prefer media and append telephony kind.
        kinds = list(media.get("kinds", []))
        for kind in telephony.get("kinds", []):
            if kind not in kinds:
                kinds.append(kind)
        merged = dict(media)
        merged["kinds"] = kinds
        for name, field in telephony.get("fields", {}).items():
            if name not in merged["fields"]:
                merged["fields"][name] = field
        secrets = list(merged.get("secrets", []))
        for name in telephony.get("secrets", []):
            if name not in secrets:
                secrets.append(name)
        if secrets:
            merged["secrets"] = secrets
        return merged
    return media if media is not None else telephony  # type: ignore[return-value]


def all_auth_catalog() -> dict[str, dict[str, Any]]:
    """All provider-level auth catalogs keyed by provider id."""
    catalog = providers_all_level_auth()
    catalog.update(telephony_all_level_auth())
    return catalog


def validate_auth_payload(provider: str, auth: dict[str, Any]) -> dict[str, Any]:
    """Validate stored-auth payload; keep **secret** fields only.

    Non-secret catalog fields (region, endpoint, project_id, …) must not be
    stored in ProviderAuth. Unknown keys and non-secret keys are rejected.
    Catalog ``required`` that are secrets must be present when listed.
    """
    catalog = provider_auth_catalog(provider)
    if not auth:
        raise ValueError("auth must not be empty")

    secrets = list(catalog.get("secrets", []))
    if not secrets:
        raise ValueError(f"Provider {provider} has no secret auth fields to store")

    allowed = set(secrets)
    unknown = sorted(set(auth) - allowed)
    if unknown:
        raise ValueError(
            f"Only secret auth fields may be stored for {provider}: "
            f"rejected {', '.join(unknown)} (allowed: {', '.join(sorted(allowed))})"
        )

    required = [name for name in catalog.get("required", []) if name in allowed]
    missing = [name for name in required if name not in auth or auth[name] in (None, "")]
    if missing:
        raise ValueError(
            f"Missing required auth fields for {provider}: {', '.join(missing)}"
        )

    return {key: auth[key] for key in secrets if key in auth}
