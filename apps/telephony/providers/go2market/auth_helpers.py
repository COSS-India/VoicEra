"""Go To Market Integrations profile parsing and resolution."""

from __future__ import annotations

import json
import re
from typing import Any

from .helpers import normalize_phoneno

_PHONE_DIGITS = re.compile(r"\D+")


class Go2MarketAuthError(ValueError):
    """Invalid Go To Market OBD profile auth."""


def _normalize_serviceno(raw: str) -> str:
    digits = _PHONE_DIGITS.sub("", str(raw or "").strip().lstrip("+"))
    if len(digits) == 10 and digits.isdigit():
        return digits
    if digits.startswith("91") and len(digits) == 12:
        return digits[2:]
    return digits


def _pair(serviceno: Any, ukey: Any, ivrtemplateid: Any) -> dict[str, str]:
    service = _normalize_serviceno(str(serviceno or ""))
    key = str(ukey or "").strip()
    template = str(ivrtemplateid or "").strip()
    if not service or not service.isdigit() or len(service) != 10:
        raise Go2MarketAuthError(
            "serviceno must be a 10-digit Indian mobile (service number)"
        )
    if not key:
        raise Go2MarketAuthError("ukey is required")
    if not template:
        raise Go2MarketAuthError("ivrtemplateid is required")
    return {
        "serviceno": service,
        "ukey": key,
        "ivrtemplateid": template,
    }


def parse_obd_profiles(raw: str | list | None) -> list[dict[str, str]]:
    """Parse ProviderAuth ``obd_profiles`` into profile dicts."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise Go2MarketAuthError("obd_profiles is required and must not be empty")

    data: Any = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise Go2MarketAuthError(
                'obd_profiles must be a JSON array of '
                '{"serviceno":"...","ukey":"...","ivrtemplateid":"..."} objects'
            ) from exc

    if not isinstance(data, list) or not data:
        raise Go2MarketAuthError("obd_profiles must be a non-empty JSON array")

    profiles: list[dict[str, str]] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise Go2MarketAuthError(f"obd_profiles[{index}] must be an object")
        try:
            profiles.append(
                _pair(
                    item.get("serviceno"),
                    item.get("ukey"),
                    item.get("ivrtemplateid"),
                )
            )
        except Go2MarketAuthError as exc:
            raise Go2MarketAuthError(f"obd_profiles[{index}]: {exc}") from exc
    return profiles


def serialize_obd_profiles(profiles: list[dict[str, str]]) -> str:
    return json.dumps(parse_obd_profiles(profiles), separators=(",", ":"))


def list_service_numbers(profiles: str | list | None) -> list[str]:
    return [p["serviceno"] for p in parse_obd_profiles(profiles)]


def resolve_obd_profile(
    profiles: str | list | None,
    from_number: str | None = None,
) -> dict[str, str]:
    """Pick the profile for outbound dialing."""
    pairs = parse_obd_profiles(profiles)
    if not from_number:
        if len(pairs) == 1:
            return pairs[0]
        raise Go2MarketAuthError(
            "from_number is required when multiple Go To Market profiles are configured"
        )

    target = normalize_phoneno(from_number)
    target_service = _normalize_serviceno(from_number)
    for pair in pairs:
        if pair["serviceno"] == target or pair["serviceno"] == target_service:
            return pair

    configured = ", ".join(p["serviceno"] for p in pairs)
    raise Go2MarketAuthError(
        f"from_number={from_number!r} does not match any configured serviceno "
        f"({configured})"
    )
