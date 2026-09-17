"""VI phone inventory helpers (Integrations auth number_flows)."""

from __future__ import annotations

from apps.telephony.providers.vi.config import ViConfig


def require_phone_in_inventory(config: ViConfig, phone_number: str) -> None:
    """Raise ValueError when phone is not configured in auth number_flows."""
    config.resolve_dial_context(phone_number)


def filter_phones_in_inventory(
    config: ViConfig, phone_numbers: list[str]
) -> list[str]:
    """Return phones that exist in auth number_flows."""
    filtered: list[str] = []
    for phone in phone_numbers:
        try:
            require_phone_in_inventory(config, phone)
        except ValueError:
            continue
        if phone not in filtered:
            filtered.append(phone)
    return filtered
