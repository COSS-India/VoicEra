"""VI application stubs and OBD dial entrypoints."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

from apps.telephony.base import fail, success
from apps.telephony.providers.vi.obd.errors import ViObdError

if TYPE_CHECKING:
    from apps.telephony.providers.vi.client import ViClient

VI_STUB_APP_ID = "vi-local"


async def create_application(
    client: "ViClient", app_name: str, answer_url: str
) -> Dict[str, Any]:
    del app_name, answer_url
    return success(
        "VI uses a portal DIY flow; no provider application created",
        app_id=VI_STUB_APP_ID,
    )


async def delete_application(
    client: "ViClient", application_id: str
) -> Dict[str, Any]:
    del client, application_id
    return success("VI stub application deleted (no-op)")


async def update_application_name(
    client: "ViClient", application_id: str, app_name: str
) -> Dict[str, Any]:
    del client, application_id, app_name
    return success("VI stub application rename (no-op)")


async def link_number(
    client: "ViClient", phone_number: str, application_id: str
) -> Dict[str, Any]:
    del client, application_id
    return success(
        "VI number linked locally only (portal routing uses Numbers inventory)",
        phone_number=phone_number,
    )


async def unlink_number(client: "ViClient", phone_number: str) -> Dict[str, Any]:
    del client
    return success(
        "VI number unlinked locally only (no-op on provider)",
        phone_number=phone_number,
    )


async def list_numbers(client: "ViClient") -> Dict[str, Any]:
    """Return phones configured in org Integrations auth."""
    numbers = client.config.list_inventory_phones()
    return success(
        "VI numbers from Integrations auth configuration",
        numbers=numbers,
    )


def _agent_id_from_answer_url(answer_url: str) -> str:
    try:
        query = parse_qs(urlparse(answer_url).query)
        values = query.get("agent_id") or []
        if values and str(values[0]).strip():
            return str(values[0]).strip()
    except Exception:
        pass
    return "unknown"


def _resolve_dial_params(
    client: "ViClient",
    *,
    from_number: str,
    flow_id: Optional[str],
    fallback_phone: Optional[str],
) -> tuple[str, str]:
    if flow_id and fallback_phone:
        return flow_id.strip(), fallback_phone.strip()

    phone = (from_number or fallback_phone or "").strip()
    if not phone:
        raise ViObdError(
            "VI outbound requires from_number or fallback_phone to resolve flow_id"
        )
    ctx = client.config.resolve_dial_context(phone)
    return ctx["flow_id"], ctx["fallback_phone"]


async def initiate_call(
    client: "ViClient",
    *,
    from_number: str,
    to_number: str,
    answer_url: str,
    answer_method: str = "POST",
    hangup_url: Optional[str] = None,
    hangup_method: str = "POST",
    flow_id: Optional[str] = None,
    fallback_phone: Optional[str] = None,
) -> Dict[str, Any]:
    """Queue a single outbound via VI OBD (1-row campaign)."""
    del answer_method, hangup_url, hangup_method
    agent_id = _agent_id_from_answer_url(answer_url)

    try:
        resolved_flow_id, resolved_fallback = _resolve_dial_params(
            client,
            from_number=from_number,
            flow_id=flow_id,
            fallback_phone=fallback_phone,
        )
    except (ViObdError, ValueError) as exc:
        return fail(str(exc))

    def _run() -> dict:
        obd = client.obd_client()
        return obd.place_single_outbound_call(
            to_number,
            agent_id=agent_id,
            flow_id=resolved_flow_id,
            fallback_phone=resolved_fallback,
        )

    try:
        result = await asyncio.to_thread(_run)
    except ViObdError as exc:
        return fail(str(exc))

    campaign_ref = result.get("campaign_Ref_ID")
    return success(
        str(result.get("message") or "VI outbound queued"),
        call_uuid=str(campaign_ref) if campaign_ref is not None else None,
        request_uuid=str(campaign_ref) if campaign_ref is not None else None,
        campaign_Ref_ID=campaign_ref,
        campainKey=result.get("campainKey"),
        dni=result.get("dni"),
        msisdn=result.get("msisdn"),
        flow_id=resolved_flow_id,
        raw=result,
    )
