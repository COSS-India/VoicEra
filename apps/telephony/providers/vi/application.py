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
from .pull_report import (
    ViPullReportClient,
    ViPullReportError,
    campaign_dni,
    map_pull_row,
    obd_campaign_ids,
    pull_base_from_obd_base,
    resolve_pull_window,
    summarize_rows,
)

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
    fromdate: Optional[str] = None,
    todate: Optional[str] = None,
    fromtime: Optional[str] = None,
    totime: Optional[str] = None,
    dialtimeout: Optional[int] = None,
    retrycount: Optional[int] = None,
    retryintervalvalue: Optional[int] = None,
    retryintervaltype: Optional[int] = None,
) -> Dict[str, Any]:
    """Create one OBD campaign and ingest many MSISDNs."""

    def _run() -> dict:
        return _obd_client(client).place_bulk_outbound_calls(
            to_numbers,
            from_number=from_number,
            name=name,
            description=description,
            fromdate=fromdate,
            todate=todate,
            fromtime=fromtime,
            totime=totime,
            dialtimeout=dialtimeout,
            retrycount=retrycount,
            retryintervalvalue=retryintervalvalue,
            retryintervaltype=retryintervaltype,
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


def _as_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def map_obd_status_body(
    body: Mapping[str, Any] | None,
    *,
    campaign_id: str | None = None,
) -> dict[str, Any]:
    """Flatten campaignstatus ``data`` for the status dialog."""
    payload = body if isinstance(body, dict) else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    base = data.get("baseDetails") if isinstance(data.get("baseDetails"), dict) else {}
    return {
        "campaign_id": campaign_id,
        "campaign_name": data.get("campaignName"),
        "campaign_type": data.get("campaignType"),
        "current_status": data.get("currentStatus"),
        "total_base_received": _as_int(base.get("totalBaseReceived")),
        "total_call_initiated": _as_int(base.get("totalCallInitiated")),
        "total_calls_connected": _as_int(base.get("totalCallsConnected")),
        "total_calls_not_connected": _as_int(base.get("totalCallsNotConnected")),
        "remaining_in_queue": _as_int(base.get("remainingNumbersInQueue")),
        "success_rate_percentage": _as_float(base.get("successRatePercentage")),
        "retry_interval": data.get("retryInterval"),
        "retry_within": _as_int(data.get("retryWithin")),
        "retry_attempts": _as_int(data.get("retryAttempts")),
        "created_time": data.get("campaignCreatedTime"),
        "window": data.get("campaignWindow"),
        "end_date": data.get("campaignEndDate"),
    }


def _status_for_id(
    obd: ViObdClient,
    token: str,
    campaign_id: str,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    handles = metadata.get("bulk_provider_handles")
    if not isinstance(handles, dict):
        handles = {}
    latest_key = str(handles.get("campain_key") or "").strip()
    ref = handles.get("campaign_ref_id")
    if ref is None:
        ref = metadata.get("bulk_provider_call_sid")
    if campaign_id == latest_key and ref is not None and str(ref).strip():
        body, _kind = obd.get_campaign_status_with_fallback(
            token, ref, campain_key=campaign_id
        )
    else:
        body, status = obd.get_campaign_status(token, campaign_id, id_kind="campainKey")
        if status != 200:
            raise ViObdError(
                f"campaignstatus failed (HTTP {status}) for campaign_ID={campaign_id!r}"
            )
    return map_obd_status_body(body if isinstance(body, dict) else None, campaign_id=campaign_id)


async def get_obd_status(client: "ViClient", *, metadata: Mapping[str, Any]) -> Dict[str, Any]:
    """Fetch campaignstatus for each stored OBD campaign id."""
    ids = obd_campaign_ids(metadata)
    if not ids:
        return fail(
            "This campaign has not been submitted to the provider yet",
            code="missing_campaign",
        )

    def _run() -> list[dict[str, Any]]:
        obd = _obd_client(client)
        token, _ = obd.get_auth_token()
        return [_status_for_id(obd, token, campaign_id, metadata) for campaign_id in ids]

    try:
        statuses = await asyncio.to_thread(_run)
    except ViObdError as exc:
        return fail(str(exc))
    return success("OBD campaign status", statuses=statuses)


async def get_obd_report(
    client: "ViClient",
    *,
    metadata: Mapping[str, Any],
    from_number: str | None = None,
    started_at: str | None = None,
) -> Dict[str, Any]:
    """Fetch outbound pullreport rows for each stored OBD campaign id."""
    if not client.pull_username or not client.pull_password:
        return fail(
            "Pull API credentials are not configured",
            code="missing_credentials",
        )
    ids = obd_campaign_ids(metadata)
    if not ids:
        return fail(
            "This campaign has not been submitted to the provider yet",
            code="missing_campaign",
        )
    dni = campaign_dni(metadata, from_number)
    if len(dni) != 10:
        return fail(
            "Campaign caller number must be a 10-digit DNI",
            code="missing_dni",
        )
    obd_config = metadata.get("obd_config")
    if not isinstance(obd_config, dict):
        obd_config = {}
    fromdate, todate = resolve_pull_window(
        str(obd_config.get("fromdate") or "") or None,
        str(obd_config.get("todate") or "") or None,
        started_at,
    )

    def _run() -> list[dict[str, Any]]:
        pull = ViPullReportClient(
            client.pull_username,
            client.pull_password,
            pull_base=pull_base_from_obd_base(client.base_url),
        )
        token = pull.authenticate(dni)
        rows: list[dict[str, Any]] = []
        for campaign_id in ids:
            for raw in pull.pull_campaign(
                token,
                dni=dni,
                campaign_id=campaign_id,
                fromdate=fromdate,
                todate=todate,
            ):
                rows.append(map_pull_row(raw))
        return rows

    try:
        rows = await asyncio.to_thread(_run)
    except ViPullReportError as exc:
        return fail(str(exc), code=exc.code)
    return success("OBD call report", summary=summarize_rows(rows), rows=rows)
