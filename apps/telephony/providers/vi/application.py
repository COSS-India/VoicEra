"""VI application stubs + OBD dial helpers.

VI has no carrier application/number APIs. DIY Streaming is configured in the
portal; this module keeps the Vobiz/Plivo client method surface working.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional
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
    sid = str(campaign_ref) if campaign_ref is not None else None
    return success(
        queued.get("message") or "VI outbound queued",
        provider_call_sid=sid,
        from_number=queued.get("dni"),
        provider_handles={
            "campaign_ref_id": campaign_ref,
            "campain_key": queued.get("campainKey"),
        },
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
    sid = str(campaign_ref) if campaign_ref is not None else None
    return success(
        queued.get("message") or "VI bulk outbound queued",
        provider_call_sid=sid,
        from_number=queued.get("dni"),
        provider_handles={
            "campaign_ref_id": campaign_ref,
            "campain_key": queued.get("campainKey"),
        },
        raw=queued,
    )


_TERMINAL_COMPLETED = frozenset(
    {"completed", "complete", "finished", "expired", "cancelled"}
)
_TERMINAL_FAILED = frozenset({"failed", "fail", "error"})


def _normalize_bulk_state(body: Mapping[str, Any] | None) -> str:
    """Map VI campaignstatus body to contract ``state``."""
    if not body:
        return "unknown"
    raw = body.get("campaignStatus") or body.get("status") or ""
    state = str(raw).strip().lower()
    if not state:
        return "unknown"
    if state in _TERMINAL_COMPLETED:
        return "completed"
    if state in _TERMINAL_FAILED:
        return "failed"
    if state in {"created", "running", "inprogress", "in_progress", "active", "queued"}:
        return "running"
    return state if state in {"running", "completed", "failed", "unknown"} else "running"


async def get_bulk_status(
    client: "ViClient",
    *,
    provider_call_sid: str | int | None,
    provider_handles: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Poll VI campaignstatus; return normalized ``state`` for API callers."""
    handles = dict(provider_handles or {})
    campaign_ref_id = handles.get("campaign_ref_id")
    if campaign_ref_id is None:
        campaign_ref_id = provider_call_sid
    campain_key = handles.get("campain_key")
    if campain_key is not None:
        campain_key = str(campain_key).strip() or None

    if campaign_ref_id is None and not campain_key:
        return fail("Bulk status requires provider_call_sid or provider_handles")

    def _run() -> tuple[dict, str]:
        obd = _obd_client(client)
        token, _ = obd.get_auth_token()
        if campaign_ref_id is not None:
            return obd.get_campaign_status_with_fallback(
                token, campaign_ref_id, campain_key=campain_key
            )
        # Handles-only path: poll by campainKey.
        body, status = obd.get_campaign_status(
            token, campain_key, id_kind="campainKey"
        )
        if status != 200:
            raise ViObdError(
                f"campaignstatus failed (HTTP {status}) for campainKey={campain_key!r}: {body}"
            )
        return body, "campainKey"

    try:
        body, id_kind = await asyncio.to_thread(_run)
    except ViObdError as exc:
        return fail(str(exc))
    return success(
        "VI campaign status",
        state=_normalize_bulk_state(body if isinstance(body, dict) else None),
        raw={"id_kind": id_kind, "status_body": body},
    )
