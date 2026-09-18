"""VI application stubs + OBD dial helpers.

VI has no carrier application/number APIs. DIY Streaming is configured in the
portal; this module keeps the Vobiz/Plivo client method surface working.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from apps.telephony.base import fail, success

from .auth_helpers import answer_url_to_vi_stream, list_dnis
from .obd_client import ViObdClient, ViObdError

if TYPE_CHECKING:
    from apps.telephony.providers.vi.client import ViClient

logger = logging.getLogger(__name__)

VI_STUB_APP_ID = "vi-app"


def _extract_agent_id_from_answer_url(answer_url: str) -> Optional[str]:
    try:
        query = parse_qs(urlparse(answer_url).query)
        values = query.get("agent_id") or []
        if values and str(values[0]).strip():
            return str(values[0]).strip()
    except Exception:
        return None
    return None


async def create_application(
    client: "ViClient",
    app_name: str,
    answer_url: str,
) -> Dict[str, Any]:
    """Stub application; return WSS stream URL derived from the answer host."""
    del app_name
    stream_url = answer_url_to_vi_stream(answer_url)
    logger.info(
        "VI create_application stub: app_id=%s stream=%s",
        VI_STUB_APP_ID,
        stream_url,
    )
    return success(
        "VI application stub created",
        app_id=VI_STUB_APP_ID,
        answer_url=stream_url,
        hangup_url="",
    )


async def delete_application(
    client: "ViClient",
    application_id: str,
) -> Dict[str, Any]:
    del client, application_id
    return success("VI application delete is a no-op")


async def update_application_name(
    client: "ViClient",
    application_id: str,
    app_name: str,
) -> Dict[str, Any]:
    del client, application_id, app_name
    return success("VI application rename is a no-op")


async def link_number(
    client: "ViClient",
    phone_number: str,
    application_id: str,
) -> Dict[str, Any]:
    """Local inventory only — portal routes DIY flow by DNI."""
    del client, application_id
    logger.info("VI link_number no-op: phone=%s", phone_number)
    return success("VI number link is a no-op (configure DIY flow in portal)", phone_number=phone_number)


async def unlink_number(client: "ViClient", phone_number: str) -> Dict[str, Any]:
    del client
    logger.info("VI unlink_number no-op: phone=%s", phone_number)
    return success("VI number unlink is a no-op", phone_number=phone_number)


async def list_numbers(client: "ViClient") -> Dict[str, Any]:
    """Return every DNI configured in ProviderAuth."""
    try:
        numbers = list_dnis(client.dni_flows)
    except Exception as exc:
        return fail(str(exc))
    return success("VI DNIs from auth", numbers=numbers)


def _obd_client(client: "ViClient") -> ViObdClient:
    return ViObdClient(
        client.credentials.auth_id,
        client.credentials.auth_token,
        obd_base=client.base_url,
        dni_flows=client.dni_flows,
    )


async def initiate_call(
    client: "ViClient",
    *,
    from_number: str,
    to_number: str,
    answer_url: str,
    answer_method: str = "POST",
    hangup_url: Optional[str] = None,
    hangup_method: str = "POST",
) -> Dict[str, Any]:
    """Place a single outbound call via VI OBD (createCampaign + ingest)."""
    del answer_method, hangup_url, hangup_method
    agent_id = _extract_agent_id_from_answer_url(answer_url)

    def _run() -> dict:
        return _obd_client(client).place_single_outbound_call(
            to_number,
            from_number=from_number,
            agent_id=agent_id,
        )

    try:
        queued = await asyncio.to_thread(_run)
    except ViObdError as exc:
        logger.error("VI OBD dial failed: to=%s error=%s", to_number, exc)
        return fail(str(exc))

    campaign_ref = queued.get("campaign_Ref_ID")
    return success(
        queued.get("message") or "VI outbound queued",
        call_uuid=campaign_ref,
        request_uuid=campaign_ref,
        campaign_Ref_ID=campaign_ref,
        campainKey=queued.get("campainKey"),
        dni=queued.get("dni"),
        msisdn=queued.get("msisdn"),
        raw=queued,
    )


async def initiate_bulk_calls(
    client: "ViClient",
    *,
    from_number: str,
    to_numbers: List[str],
    name: Optional[str] = None,
    description: str = "VoicERA VI campaign",
) -> Dict[str, Any]:
    """Create one OBD campaign and ingest many MSISDNs."""

    def _run() -> dict:
        return _obd_client(client).place_bulk_outbound_calls(
            to_numbers,
            from_number=from_number,
            name=name,
            description=description,
        )

    try:
        queued = await asyncio.to_thread(_run)
    except ViObdError as exc:
        logger.error("VI OBD bulk dial failed: count=%s error=%s", len(to_numbers), exc)
        return fail(str(exc))

    campaign_ref = queued.get("campaign_Ref_ID")
    return success(
        queued.get("message") or "VI bulk outbound queued",
        call_uuid=campaign_ref,
        request_uuid=campaign_ref,
        campaign_Ref_ID=campaign_ref,
        campainKey=queued.get("campainKey"),
        dni=queued.get("dni"),
        msisdns=queued.get("msisdns"),
        window_hours=queued.get("window_hours"),
        raw=queued,
    )


async def get_campaign_status(
    client: "ViClient",
    *,
    campaign_ref_id: str | int,
    campain_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Poll VI campaignstatus with Ref_ID then campainKey fallback."""

    def _run() -> tuple[dict, str]:
        obd = _obd_client(client)
        token, _ = obd.get_auth_token()
        return obd.get_campaign_status_with_fallback(
            token, campaign_ref_id, campain_key=campain_key
        )

    try:
        body, id_kind = await asyncio.to_thread(_run)
    except ViObdError as exc:
        return fail(str(exc))
    return success(
        "VI campaign status",
        id_kind=id_kind,
        status_body=body,
        campaign_Ref_ID=campaign_ref_id,
        campainKey=campain_key,
    )
