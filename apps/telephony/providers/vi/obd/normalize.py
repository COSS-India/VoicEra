"""Phone normalization helpers for VI OBD."""

from __future__ import annotations

from apps.telephony.providers.vi.obd.constants import DEFAULT_OBD_BASE


def normalize_cpaas_base(base: str, default: str = DEFAULT_OBD_BASE) -> str:
    """Ensure override URLs include the /Cpaas/api/v1/ prefix."""
    value = (base or "").strip().rstrip("/") or default
    if "/Cpaas/" in value or "/cpaas/" in value.lower():
        return value
    if "/api/v1/" in value:
        return value.replace("/api/v1/", "/Cpaas/api/v1/", 1)
    return default


def normalize_msisdn(number: str) -> str:
    """Strip E.164 prefix for VI OBD (e.g. +919876543210 → 9876543210)."""
    value = str(number or "").strip().lstrip("+")
    if value.startswith("91") and len(value) > 10:
        value = value[2:]
    return value


def normalize_dni(number: str) -> str:
    """Normalize a phone to 10-digit local DNI when possible."""
    msisdn = normalize_msisdn(number)
    if len(msisdn) == 10 and msisdn.isdigit():
        return msisdn
    digits = str(number or "").strip().lstrip("+")
    if len(digits) == 10 and digits.isdigit():
        return digits
    return msisdn or digits


def normalize_e164(number: str) -> str:
    """Best-effort E.164 for inventory display."""
    raw = str(number or "").strip().replace(" ", "").replace("-", "")
    if not raw:
        return ""
    if raw.startswith("+"):
        return raw
    digits = raw.lstrip("+")
    if len(digits) == 10 and digits.isdigit():
        return f"+91{digits}"
    if digits.isdigit():
        return f"+{digits}"
    return raw


def phone_lookup_keys(number: str) -> set[str]:
    """Variants for matching agent linked phone to auth number_flows."""
    keys: set[str] = set()
    raw = str(number or "").strip()
    if not raw:
        return keys

    keys.add(raw)
    keys.add(raw.lstrip("+"))

    e164 = normalize_e164(raw)
    if e164:
        keys.add(e164)
        keys.add(e164.lstrip("+"))

    dni = normalize_dni(raw)
    if dni:
        keys.add(dni)
        keys.add(f"+91{dni}")
        keys.add(f"91{dni}")

    if raw.startswith("0") and len(raw) == 11:
        keys.add(raw[1:])
        keys.add(f"+91{raw[1:]}")

    return {k for k in keys if k}
