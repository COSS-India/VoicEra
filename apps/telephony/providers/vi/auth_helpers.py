"""VI auth helpers: DNI / flow_id pairs, resolution, and stream URL rewrite."""

from __future__ import annotations

import json
import re
from typing import Any


class ViAuthError(ValueError):
    """Invalid VI auth DNI / flow_id."""


_PHONE_DIGITS = re.compile(r"\D+")


def normalize_msisdn(number: str) -> str:
    """Strip to national MSISDN for VI OBD (e.g. +919876543210 → 9876543210)."""
    value = str(number or "").strip().lstrip("+")
    value = _PHONE_DIGITS.sub("", value)
    if value.startswith("91") and len(value) > 10:
        value = value[2:]
    return value


def normalize_dni(number: str) -> str:
    """Digits-only DNI with India country code (no ``+``).

    Accepts ``+9198…``, ``9198…``, or 10-digit national. Used for matching;
    Integrations storage uses :func:`format_dni_e164`.
    """
    digits = _PHONE_DIGITS.sub("", str(number or "").strip().lstrip("+"))
    if len(digits) == 10 and digits.isdigit():
        return f"91{digits}"
    return digits


def format_dni_e164(dni: str) -> str:
    """Canonical Integrations / inventory form: ``+91XXXXXXXXXX``."""
    digits = normalize_dni(dni)
    if not digits:
        raise ViAuthError("dni is required and must not be empty")
    if not digits.isdigit():
        raise ViAuthError(
            "dni must be an Indian mobile as +91XXXXXXXXXX "
            "(e.g. +919876543210)"
        )
    if not (digits.startswith("91") and len(digits) == 12):
        raise ViAuthError(
            "dni must be an Indian mobile as +91XXXXXXXXXX "
            "(e.g. +919876543210)"
        )
    return f"+{digits}"


def to_obd_dni_fallback(dni: str) -> str:
    """OBD ingest DNI when ``getActiveDNIList`` is unavailable.

    Matches the common working-branch ``VI_DNI`` form: country-code digits,
    no ``+`` (e.g. ``919876543210``). Prefer live portal DNI when available.
    """
    return format_dni_e164(dni).lstrip("+")


def _pair(dni: Any, flow_id: Any) -> dict[str, str]:
    """Build one auth pair; DNI is always stored as E.164 ``+91…``."""
    dni_value = format_dni_e164(str(dni or ""))
    flow_value = str(flow_id or "").strip()
    if not flow_value:
        raise ViAuthError("flow_id is required and must not be empty")
    return {"dni": dni_value, "flow_id": flow_value}


def parse_dni_flows(raw: str | list | None) -> list[dict[str, str]]:
    """Parse ProviderAuth ``dni_flows`` into ``[{dni, flow_id}, ...]``.

    Accepts a JSON array string or an already-decoded list. Each item must
    have non-empty ``dni`` and ``flow_id``. DNI values are canonicalized to
    E.164 ``+91…`` (legacy ``919…`` / 10-digit forms are accepted).
    """
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise ViAuthError("dni_flows is required and must not be empty")

    data: Any = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ViAuthError(
                "dni_flows must be a JSON array of "
                '{"dni":"...","flow_id":"..."} objects'
            ) from exc

    if not isinstance(data, list) or not data:
        raise ViAuthError("dni_flows must be a non-empty JSON array")

    pairs: list[dict[str, str]] = []
    for index, item in enumerate(data):
        if not isinstance(item, dict):
            raise ViAuthError(f"dni_flows[{index}] must be an object")
        try:
            pairs.append(_pair(item.get("dni"), item.get("flow_id")))
        except ViAuthError as exc:
            raise ViAuthError(f"dni_flows[{index}]: {exc}") from exc
    return pairs


def serialize_dni_flows(pairs: list[dict[str, str]]) -> str:
    """Serialize validated pairs to the ProviderAuth string form."""
    return json.dumps(parse_dni_flows(pairs), separators=(",", ":"))


def list_dnis(dni_flows: str | list | None) -> list[str]:
    """Return E.164 DNIs from auth for inventory listing."""
    return [format_dni_e164(pair["dni"]) for pair in parse_dni_flows(dni_flows)]


def require_dni_flow(dni: str, flow_id: str) -> tuple[str, str]:
    """Validate and return stripped ``(dni, flow_id)`` (single pair)."""
    pair = _pair(dni, flow_id)
    return pair["dni"], pair["flow_id"]


def resolve_dni_and_flow(
    dni_flows: str | list | None,
    from_number: str | None = None,
    *,
    dni: str = "",
    flow_id: str = "",
) -> tuple[str, str]:
    """Return ``(dni, flow_id)`` for dialing.

    Prefers ``dni_flows``. Legacy single ``dni``/``flow_id`` kwargs are still
    accepted. When ``from_number`` is set, pick the matching pair (digit-
    normalized); with one pair and no ``from_number``, use that pair.
    Returned ``dni`` is E.164; OBD wire form is chosen later via live
    ``getActiveDNIList`` (or :func:`to_obd_dni_fallback`).
    """
    if dni_flows is not None and str(dni_flows).strip() != "":
        pairs = parse_dni_flows(dni_flows)
    elif dni or flow_id:
        pairs = [_pair(dni, flow_id)]
    else:
        raise ViAuthError("dni_flows is required and must not be empty")

    if not from_number:
        if len(pairs) == 1:
            return pairs[0]["dni"], pairs[0]["flow_id"]
        raise ViAuthError(
            "from_number is required when multiple DNI/flow pairs are configured"
        )

    target = normalize_dni(from_number)
    target_msisdn = normalize_msisdn(from_number)
    for pair in pairs:
        dni_norm = normalize_dni(pair["dni"])
        if dni_norm == target or normalize_msisdn(pair["dni"]) == target_msisdn:
            return pair["dni"], pair["flow_id"]

    configured = ", ".join(p["dni"] for p in pairs)
    raise ViAuthError(
        f"from_number={from_number!r} does not match any configured DNI "
        f"({configured})"
    )


def resolve_vi_agent_id(
    path_agent_id: str | None,
    start_info: dict[str, Any],
) -> str | None:
    """Extract agent id from path or ``start.custom_parameters``."""
    if path_agent_id and str(path_agent_id).strip():
        return str(path_agent_id).strip()
    custom = start_info.get("custom_parameters") or start_info.get("customParameters") or {}
    if not isinstance(custom, dict):
        return None
    for key in ("agent_id", "agentId", "agent"):
        value = custom.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def answer_url_to_vi_stream(answer_url: str) -> str:
    """Rewrite an HTTP answer URL host into ``wss://…/vi/stream``."""
    raw = (answer_url or "").strip()
    if not raw:
        return "/vi/stream"
    if raw.startswith("https://"):
        host = raw[len("https://") :]
        scheme = "wss://"
    elif raw.startswith("http://"):
        host = raw[len("http://") :]
        scheme = "ws://"
    elif raw.startswith("wss://") or raw.startswith("ws://"):
        scheme, _, rest = raw.partition("://")
        host = rest
        scheme = f"{scheme}://"
    else:
        return f"wss://{raw.split('/')[0]}/vi/stream"

    host_only = host.split("/")[0].split("?")[0]
    return f"{scheme}{host_only}/vi/stream"


def phone_lookup_candidates(raw: str) -> list[str]:
    """Generate likely linked_phone_number spellings for DNI/CLI lookup.

    Handles common VI portal forms: national 10-digit, ``91…`` without ``+``,
    and E.164 ``+91…``.
    """
    value = str(raw or "").strip()
    if not value:
        return []
    digits = "".join(ch for ch in value if ch.isdigit())
    candidates: list[str] = []

    def _add(item: str) -> None:
        if item and item not in candidates:
            candidates.append(item)

    _add(value)
    if digits:
        _add(digits)
        _add(f"+{digits}")
    if digits.startswith("91") and len(digits) > 10:
        national = digits[2:]
        _add(national)
        _add(f"+{digits}")
        _add(f"+91{national}")
        _add(f"91{national}")
    elif len(digits) == 10:
        # Indian mobile without country code (common VI start.dni form).
        _add(f"91{digits}")
        _add(f"+91{digits}")
    return candidates
