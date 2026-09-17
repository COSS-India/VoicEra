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

VI_INTEGRATION_STORED_FIELDS = frozenset({"number_flows"})


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


def _validate_vi_number_flows(raw: Any) -> list[dict[str, str]]:
    from apps.telephony.providers.vi.config import ViNumberFlowEntry

    if not isinstance(raw, list) or not raw:
        raise ValueError("number_flows must be a non-empty list")

    entries: list[ViNumberFlowEntry] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"number_flows[{index}] must be an object")
        try:
            entries.append(ViNumberFlowEntry.model_validate(item))
        except Exception as exc:
            raise ValueError(f"number_flows[{index}] invalid: {exc}") from exc

    seen: set[str] = set()
    normalized: list[dict[str, str]] = []
    for entry in entries:
        key = entry.normalized_phone
        if key in seen:
            raise ValueError(f"duplicate phone number in number_flows: {entry.phone_number}")
        seen.add(key)
        normalized.append(
            {
                "phone_number": entry.normalized_phone,
                "flow_id": entry.flow_id,
            }
        )
    return normalized


def validate_auth_payload(provider: str, auth: dict[str, Any]) -> dict[str, Any]:
    """Validate stored-auth payload; keep **secret** fields only.

    Non-secret catalog fields (region, endpoint, project_id, …) must not be
    stored in ProviderAuth. Unknown keys and non-secret keys are rejected.
    Catalog ``required`` that are secrets must be present when listed.

    Vodafone Idea (``vi``) also stores non-secret ``number_flows`` in auth.
    """
    catalog = provider_auth_catalog(provider)
    if not auth:
        raise ValueError("auth must not be empty")

    secrets = list(catalog.get("secrets", []))
    if not secrets:
        raise ValueError(f"Provider {provider} has no secret auth fields to store")

    provider_key = (provider or "").strip().lower()
    stored_fields = (
        set(secrets) | VI_INTEGRATION_STORED_FIELDS
        if provider_key == "vi"
        else set(secrets)
    )
    unknown = sorted(set(auth) - stored_fields)
    if unknown:
        raise ValueError(
            f"Only allowed auth fields may be stored for {provider}: "
            f"rejected {', '.join(unknown)} (allowed: {', '.join(sorted(stored_fields))})"
        )

    required = list(catalog.get("required", []))
    missing: list[str] = []
    for name in required:
        if name not in auth:
            missing.append(name)
            continue
        value = auth[name]
        if name == "number_flows":
            if not isinstance(value, list) or not value:
                missing.append(name)
        elif value in (None, ""):
            missing.append(name)
    if missing:
        raise ValueError(
            f"Missing required auth fields for {provider}: {', '.join(missing)}"
        )

    result = {key: auth[key] for key in secrets if key in auth}
    if provider_key == "vi":
        result["number_flows"] = _validate_vi_number_flows(auth.get("number_flows"))
    return result
