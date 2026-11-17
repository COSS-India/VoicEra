"""Go To Market application stubs + OBD dial helpers."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from apps.telephony.base import fail, success

from .auth_helpers import Go2MarketAuthError, resolve_obd_profile
from .did_websocket_client import deactivate_did_websocket, replace_did_websocket
from .helpers import answer_url_to_agent_wss, extract_query_param, format_serviceno_e164
from .obd_client import Go2MarketObdClient, Go2MarketObdError

if TYPE_CHECKING:
    from apps.telephony.providers.go2market.client import Go2MarketClient

logger = logging.getLogger(__name__)

GO2MARKET_STUB_APP_ID = "go2market-app"


async def create_application(
    client: "Go2MarketClient",
    app_name: str,
    answer_url: str,
) -> Dict[str, Any]:
    """Stub application; outbound uses WSS URL in OBD Param1."""
    del app_name
    stream_url = answer_url_to_agent_wss(answer_url)
    logger.info(
        "Go2Market create_application stub: app_id=%s stream=%s",
        GO2MARKET_STUB_APP_ID,
        stream_url,
    )
    return success(
        "Go To Market application stub created",
        app_id=GO2MARKET_STUB_APP_ID,
        answer_url=stream_url,
        hangup_url="",
    )


async def delete_application(
    client: "Go2MarketClient",
    application_id: str,
) -> Dict[str, Any]:
    del client, application_id
    return success("Go To Market application delete is a no-op")


async def update_application_name(
    client: "Go2MarketClient",
    application_id: str,
    app_name: str,
) -> Dict[str, Any]:
    del client, application_id, app_name
    return success("Go To Market application rename is a no-op")


async def link_number(
    client: "Go2MarketClient",
    phone_number: str,
    application_id: str,
    *,
    stream_url: str = "",
) -> Dict[str, Any]:
    """Register DID → agent WSS via Go To Market DID-WebSocket API."""
    del application_id
    wss = (stream_url or "").strip()
    if not wss:
        return fail(
            "Go To Market attach requires agent telephony.answer_url (WSS)",
            phone_number=phone_number,
        )
    try:
        profile = resolve_obd_profile(client.obd_profiles, phone_number)
    except Go2MarketAuthError as exc:
        return fail(str(exc), phone_number=phone_number)

    def _run() -> Any:
        # Update an existing DID mapping, or POST when the DID is new.
        return replace_did_websocket(
            client.base_url,
            ukey=profile["ukey"],
            did=profile["serviceno"],
            websocketurl=wss,
        )

    try:
        body = await asyncio.to_thread(_run)
    except Go2MarketObdError as exc:
        logger.error(
            "Go2Market DID-WebSocket link failed: did=%s error=%s",
            profile["serviceno"],
            exc,
        )
        return fail(str(exc), phone_number=phone_number)

    logger.info(
        "Go2Market DID-WebSocket linked: did=%s wss=%s",
        profile["serviceno"],
        wss,
    )
    return success(
        "Go To Market DID linked to WebSocket",
        phone_number=phone_number,
        did=profile["serviceno"],
        websocketurl=wss,
        raw=body,
    )


async def unlink_number(client: "Go2MarketClient", phone_number: str) -> Dict[str, Any]:
    """Deactivate DID → WSS mapping (idempotent if no mapping exists)."""
    try:
        profile = resolve_obd_profile(client.obd_profiles, phone_number)
    except Go2MarketAuthError as exc:
        return fail(str(exc), phone_number=phone_number)

    def _run() -> bool:
        return deactivate_did_websocket(
            client.base_url,
            ukey=profile["ukey"],
            did=profile["serviceno"],
        )

    try:
        deactivated = await asyncio.to_thread(_run)
    except Go2MarketObdError as exc:
        logger.error(
            "Go2Market DID-WebSocket unlink failed: did=%s error=%s",
            profile["serviceno"],
            exc,
        )
        return fail(str(exc), phone_number=phone_number)

    message = (
        "Go To Market DID WebSocket deactivated"
        if deactivated
        else "Go To Market DID WebSocket mapping not found (already detached)"
    )
    return success(
        message,
        phone_number=phone_number,
        did=profile["serviceno"],
        deactivated=deactivated,
    )


async def list_numbers(client: "Go2MarketClient") -> Dict[str, Any]:
    numbers = [
        format_serviceno_e164(p["serviceno"]) for p in client.obd_profiles
    ]
    return success("Go To Market service numbers from auth", numbers=numbers)


def _obd_client(client: "Go2MarketClient", from_number: str) -> Go2MarketObdClient:
    try:
        profile = resolve_obd_profile(client.obd_profiles, from_number)
    except Go2MarketAuthError as exc:
        raise Go2MarketObdError(str(exc)) from exc
    return Go2MarketObdClient(
        profile["ukey"],
        profile["serviceno"],
        profile["ivrtemplateid"],
        obd_base=client.base_url,
        campaigntype=client.campaigntype,
        retryatmpt=client.retryatmpt,
        retryduration=client.retryduration,
    )


async def initiate_call(
    client: "Go2MarketClient",
    *,
    from_number: str,
    to_number: str,
    answer_url: str,
    answer_method: str = "POST",
    hangup_url: Optional[str] = None,
    hangup_method: str = "POST",
) -> Dict[str, Any]:
    """Place a single outbound call via CreateOBDCampaignPost."""
    del answer_method, hangup_url, hangup_method
    wss_url = answer_url_to_agent_wss(answer_url)
    call_id = extract_query_param(answer_url, "call_id")

    def _run() -> dict:
        return _obd_client(client, from_number).place_single_outbound_call(
            to_number,
            wss_url=wss_url,
            call_id=call_id,
        )

    try:
        queued = await asyncio.to_thread(_run)
    except Go2MarketObdError as exc:
        logger.error("Go2Market OBD dial failed: to=%s error=%s", to_number, exc)
        return fail(str(exc))

    sid = queued.get("provider_call_sid")
    serviceno = queued.get("serviceno") or client.serviceno
    return success(
        queued.get("message") or "Go To Market outbound queued",
        provider_call_sid=str(sid) if sid is not None else None,
        from_number=format_serviceno_e164(str(serviceno)),
        raw=queued,
    )


async def initiate_bulk_calls(
    client: "Go2MarketClient",
    *,
    from_number: str,
    to_numbers: List[str],
    name: Optional[str] = None,
    description: str = "VoicERA Go To Market campaign",
) -> Dict[str, Any]:
    del client, from_number, to_numbers, name, description
    return fail("Go To Market bulk outbound is not implemented yet")
