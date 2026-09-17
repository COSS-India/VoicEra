"""VI OBD bulk campaign dispatch (one createCampaign + bulk ingest per batch)."""

from __future__ import annotations

import asyncio
import logging
import math
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from apps.telephony.providers.vi.client import ViClient
from apps.telephony.providers.vi.obd.dni import resolve_dni
from apps.telephony.providers.vi.obd.errors import ViObdError
from apps.telephony.providers.vi.obd.ingest import campain_key_from_response
from apps.telephony.providers.vi.obd.normalize import normalize_e164, normalize_msisdn

logger = logging.getLogger(__name__)

VI_STATUS_POLL_SECS = int(os.environ.get("VI_OBD_STATUS_POLL_SECS", "30"))
VI_STATUS_POLL_MAX_ROUNDS = int(os.environ.get("VI_OBD_STATUS_POLL_MAX_ROUNDS", "120"))


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_from_number(dni: str) -> str:
    cleaned = str(dni or "").strip()
    if not cleaned:
        return "+0000000000"
    if cleaned.startswith("+"):
        return cleaned
    return f"+{cleaned.lstrip('+')}"


def _format_to_number(raw: str, msisdn: str) -> str:
    phone = str(raw or msisdn or "").strip()
    if not phone:
        return f"+{msisdn}"
    if phone.startswith("+"):
        return phone
    return f"+{phone.lstrip('+')}"


async def process_vi_batch(
    campaign: dict[str, Any],
    queued_runs: list[dict[str, Any]],
    *,
    client: ViClient,
    agent: dict[str, Any],
    from_number: str,
    update_queued_run: Callable[..., None],
    update_campaign: Callable[..., None],
    create_call_log: Callable[[dict[str, Any]], Any],
    get_campaign: Callable[[str], dict[str, Any] | None],
    on_obd_failure: Callable[[str], None] | None = None,
) -> int:
    """Create one VI OBD campaign and bulk-ingest all claimed MSISDNs."""
    org_id = str(campaign["org_id"])
    agent_id = str(campaign["agent_id"])
    campaign_id = str(campaign["campaign_id"])

    ctx = client.config.resolve_dial_context(from_number)
    flow_id = ctx["flow_id"]
    fallback_phone = ctx["fallback_phone"]

    valid: list[tuple[dict[str, Any], str]] = []
    for queued_run in queued_runs:
        context = dict(queued_run.get("context_variables") or {})
        phone = str(context.get("phone_number") or "").strip()
        msisdn = normalize_msisdn(phone)
        if not msisdn:
            update_queued_run(
                str(queued_run["queued_run_id"]),
                state="failed",
                processed_at=_now_iso(),
            )
            continue
        valid.append((queued_run, msisdn))

    if not valid:
        return 0

    msisdns = [m for _, m in valid]
    window_hours = max(1.0, math.ceil(len(msisdns) / 50.0))
    logger.info(
        "VI campaign %s: starting OBD for %d contacts (flow_id=%s window_hours=%.1f)",
        campaign_id[:8],
        len(msisdns),
        flow_id,
        window_hours,
    )

    def _obd_run() -> dict[str, Any]:
        obd = client.obd_client()
        token, _ = obd.get_auth_token()
        dni, dni_source, _ = resolve_dni(
            obd, token, flow_id, fallback_phone=fallback_phone
        )
        logger.info(
            "VI campaign %s: resolved DNI %s via %s for %d contacts",
            campaign_id[:8],
            dni,
            dni_source,
            len(msisdns),
        )
        create_response = obd.create_campaign(
            token,
            flow_id=flow_id,
            name=f"campaign-{campaign_id[:8]}-{agent_id[:8]}",
            description=f"VoicERA campaign {campaign_id}",
            window_hours=window_hours,
        )
        campain_key = campain_key_from_response(create_response)
        campaign_ref_id = create_response.get("campaign_Ref_ID")
        logger.info(
            "VI campaign %s: createCampaign ok campaign_Ref_ID=%s campainKey=%s",
            campaign_id[:8],
            campaign_ref_id,
            campain_key,
        )
        obd.upload_call_list_bulk(token, campain_key, dni, msisdns)
        return {
            "dni": dni,
            "dni_source": dni_source,
            "campainKey": campain_key,
            "campaign_Ref_ID": campaign_ref_id,
            "token": token,
        }

    try:
        obd_result = await asyncio.to_thread(_obd_run)
    except ViObdError as exc:
        logger.error("VI campaign %s worker failed: %s", campaign_id[:8], exc)
        for queued_run, _ in valid:
            update_queued_run(
                str(queued_run["queued_run_id"]),
                state="failed",
                processed_at=_now_iso(),
            )
        if on_obd_failure:
            on_obd_failure(str(exc))
        raise

    campaign_ref = obd_result.get("campaign_Ref_ID")
    campain_key = obd_result.get("campainKey")
    dni = str(obd_result.get("dni") or "")
    from_e164 = normalize_e164(from_number) or _format_from_number(dni)
    now = _now_iso()
    processed_count = 0

    metadata = dict(campaign.get("orchestrator_metadata") or {})
    metadata["vi_campaign_ref_id"] = campaign_ref
    metadata["vi_campain_key"] = campain_key
    metadata["vi_dni"] = dni
    metadata["vi_current_status"] = "Created"
    update_campaign(campaign_id, orchestrator_metadata=metadata)

    logger.info(
        "VI campaign %s: campaign_Ref_ID=%s ingested %d numbers",
        campaign_id[:8],
        campaign_ref,
        len(msisdns),
    )

    for queued_run, msisdn in valid:
        qid = str(queued_run["queued_run_id"])
        context = dict(queued_run.get("context_variables") or {})
        call_id = str(uuid.uuid4())
        to_number = _format_to_number(str(context.get("phone_number") or ""), msisdn)

        variables = {k: v for k, v in context.items() if k != "phone_number"}
        variables.update(
            {
                "campaign_id": campaign_id,
                "source_uuid": queued_run.get("source_uuid"),
                "caller_number": from_e164,
                "called_number": to_number,
                "direction": "outbound",
                "vi_campaign_ref_id": campaign_ref,
            }
        )

        call_doc: dict[str, Any] = {
            "call_id": call_id,
            "provider_call_sid": str(campaign_ref) if campaign_ref is not None else None,
            "org_id": org_id,
            "agent_id": agent_id,
            "agent_name": agent.get("name"),
            "call_type": "outbound",
            "status": "ringing",
            "call_response": "pending",
            "from_number": from_e164,
            "to_number": to_number,
            "telephony_provider": "vi",
            "custom_variables": variables,
            "campaign_id": campaign_id,
            "queued_run_id": qid,
            "created_at": now,
            "updated_at": now,
            "start_time_utc": now,
            "end_time_utc": None,
            "duration": None,
            "recording_url": None,
            "transcript_url": None,
            "error_message": None,
        }
        try:
            create_call_log(call_doc)
            update_queued_run(
                qid,
                state="processed",
                call_id=call_id,
                processed_at=now,
            )
            processed_count += 1
        except Exception as exc:
            logger.warning("VI campaign CallLog failed for %s: %s", qid, exc)
            update_queued_run(qid, state="failed", processed_at=now)

    current_processed = int(campaign.get("processed_rows") or 0) + processed_count
    update_campaign(campaign_id, processed_rows=current_processed)

    await poll_vi_campaign_status(
        campaign_id=campaign_id,
        campaign_ref_id=campaign_ref,
        campain_key=str(campain_key or ""),
        expected_count=len(msisdns),
        token=str(obd_result.get("token") or ""),
        client=client,
        get_campaign=get_campaign,
        update_campaign=update_campaign,
    )

    return processed_count


async def poll_vi_campaign_status(
    *,
    campaign_id: str,
    campaign_ref_id: Any,
    campain_key: str,
    expected_count: int,
    token: str,
    client: ViClient,
    get_campaign: Callable[[str], dict[str, Any] | None],
    update_campaign: Callable[..., None],
) -> None:
    """Poll VI campaignstatus and log dial progress."""
    if campaign_ref_id is None and not campain_key:
        logger.warning(
            "VI campaign %s: skipping status poll (no campaign_Ref_ID/campainKey)",
            campaign_id[:8],
        )
        return

    if VI_STATUS_POLL_MAX_ROUNDS <= 0:
        logger.info(
            "VI campaign %s: status poll disabled (VI_OBD_STATUS_POLL_MAX_ROUNDS=%s)",
            campaign_id[:8],
            VI_STATUS_POLL_MAX_ROUNDS,
        )
        return

    logger.info(
        "VI campaign %s: starting status poll campaign_Ref_ID=%s "
        "(interval=%ss max_rounds=%s expected=%d)",
        campaign_id[:8],
        campaign_ref_id,
        VI_STATUS_POLL_SECS,
        VI_STATUS_POLL_MAX_ROUNDS,
        expected_count,
    )

    def _status_once() -> tuple[dict[str, Any], str]:
        obd = client.obd_client()
        auth_token = token
        if not auth_token:
            auth_token, _ = obd.get_auth_token()
        try:
            return obd.get_campaign_status_with_fallback(
                auth_token,
                campaign_ref_id,
                campain_key=campain_key or None,
            )
        except ViObdError:
            auth_token, _ = obd.get_auth_token(force_refresh=True)
            return obd.get_campaign_status_with_fallback(
                auth_token,
                campaign_ref_id,
                campain_key=campain_key or None,
            )

    for round_idx in range(1, VI_STATUS_POLL_MAX_ROUNDS + 1):
        latest = get_campaign(campaign_id) or {}
        state = str(latest.get("state") or "")
        if state in ("paused", "stopped", "failed", "completed", "cancelled"):
            logger.info(
                "VI campaign %s: stopping status poll early (state=%s)",
                campaign_id[:8],
                state,
            )
            return

        try:
            status_body, id_kind = await asyncio.to_thread(_status_once)
        except ViObdError as exc:
            logger.warning(
                "VI campaign %s status poll failed (round=%d): %s",
                campaign_id[:8],
                round_idx,
                exc,
            )
        else:
            data = status_body.get("data") or {}
            base_details = data.get("baseDetails") or {}
            current_status = data.get("currentStatus")
            attempted = int(base_details.get("totalCallInitiated") or 0)
            successful = int(base_details.get("totalCallsConnected") or 0)
            failed = int(base_details.get("totalCallsNotConnected") or 0)
            remaining = int(base_details.get("remainingNumbersInQueue") or 0)

            logger.info(
                "VI campaign %s status: round=%d id_kind=%s currentStatus=%s "
                "initiated=%s connected=%s not_connected=%s remaining=%s",
                campaign_id[:8],
                round_idx,
                id_kind,
                current_status,
                attempted,
                successful,
                failed,
                remaining,
            )

            metadata = dict(latest.get("orchestrator_metadata") or {})
            metadata["vi_current_status"] = current_status
            metadata["vi_base_details"] = base_details
            metadata["vi_attempted_calls"] = max(attempted, expected_count)
            metadata["vi_successful_calls"] = successful
            metadata["vi_failed_calls"] = failed
            update_campaign(campaign_id, orchestrator_metadata=metadata)

            if remaining == 0 and attempted >= expected_count:
                logger.info(
                    "VI campaign %s: OBD dialing finished "
                    "(initiated=%s connected=%s not_connected=%s)",
                    campaign_id[:8],
                    attempted,
                    successful,
                    failed,
                )
                return

        await asyncio.sleep(VI_STATUS_POLL_SECS)

    logger.warning(
        "VI campaign %s: status poll reached max rounds (%s) without completion",
        campaign_id[:8],
        VI_STATUS_POLL_MAX_ROUNDS,
    )
