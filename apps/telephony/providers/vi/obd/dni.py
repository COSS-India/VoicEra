"""VI OBD DNI resolution."""

from __future__ import annotations

import logging
from typing import Any

from apps.telephony.providers.vi.obd.errors import ViObdError
from apps.telephony.providers.vi.obd.normalize import normalize_dni

logger = logging.getLogger(__name__)


def resolve_dni(
    client: Any,
    token: str,
    flow_id: str,
    *,
    fallback_phone: str,
) -> tuple[str, str, list[str]]:
    """Resolve outbound DNI — live lookup first, fallback phone from auth/config."""
    flow = (flow_id or "").strip()
    if not flow:
        raise ViObdError("flow_id is required for VI OBD dial")

    fallback = normalize_dni(fallback_phone)
    if not fallback:
        raise ViObdError("fallback_phone is required for VI OBD DNI resolution")

    try:
        body = client.get_active_dni(token, flow)
        dni_list = [str(x) for x in (body.get("dniList") or []) if str(x).strip()]
        if dni_list:
            chosen = dni_list[0]
            logger.info(
                "VI DNI resolved via getActiveDNIList: %s (from %d options)",
                chosen,
                len(dni_list),
            )
            return chosen, "getActiveDNIList", dni_list
        logger.warning("getActiveDNIList returned empty dniList for flowId=%s", flow)
    except ViObdError as exc:
        logger.warning(
            "getActiveDNIList failed, falling back to configured phone: %s", exc
        )

    logger.info("VI DNI resolved via configured phone fallback: %s", fallback)
    return fallback, "configured_phone", [fallback]
