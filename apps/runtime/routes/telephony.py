"""Telephony answer webhook — return Stream XML pointing at our WebSocket."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response
from loguru import logger

from apps.runtime.constants import telephony_sample_rate, voice_server_ws_base
from apps.runtime.services.agent_routing import (
    AgentRoutingError,
    agent_category,
    telephony_provider,
)
from apps.runtime.services.backend import BackendError, backend_client
from apps.telephony import (
    build_answer_stream_xml,
    decode_webhook_body,
    is_hangup_event,
    map_hangup_call_response,
    merge_webhook_payload,
    parse_webhook_form,
)

router = APIRouter()


def _websocket_url_for_agent(
    org_id: str,
    agent_id: str,
    call_id: str | None = None,
) -> str:
    """Return the media WebSocket URL, optionally with ``call_id`` for CallLog correlation."""
    base = f"{voice_server_ws_base()}/agent/{org_id}/{agent_id}"
    if call_id:
        return f"{base}?{urlencode({'call_id': call_id})}"
    return base


@router.api_route("/answer", methods=["GET", "POST"])
async def telephony_answer(request: Request) -> Response:
    """Telephony answer webhook — return Stream XML pointing at our WebSocket."""
    agent_id = (request.query_params.get("agent_id") or "").strip()
    org_id = (request.query_params.get("org_id") or "").strip()
    query_call_id = (request.query_params.get("call_id") or "").strip() or None
    if not agent_id:
        return PlainTextResponse("agent_id is required", status_code=400)
    if not org_id:
        return PlainTextResponse("org_id is required", status_code=400)

    form_dict = decode_webhook_body(await request.body())
    if not form_dict:
        try:
            form_dict = dict(await request.form())
        except Exception:
            form_dict = {}

    merged = merge_webhook_payload(form_dict, request.query_params)
    webhook = parse_webhook_form(merged)
    if is_hangup_event(webhook.event):
        logger.info(
            "Telephony hangup org_id={} agent_id={} provider_call_sid={}",
            org_id,
            agent_id,
            webhook.provider_call_sid or "n/a",
        )
        patch: dict[str, str] = {
            "end_time_utc": datetime.now(timezone.utc).isoformat(),
            "status": "completed",
        }
        call_response = map_hangup_call_response(
            webhook.call_status,
            webhook.hangup_cause,
        )
        if call_response:
            patch["call_response"] = call_response
        try:
            if query_call_id:
                await backend_client.update_call(query_call_id, org_id, patch)
            elif webhook.provider_call_sid:
                await backend_client.update_call_by_provider_sid(
                    org_id,
                    webhook.provider_call_sid,
                    patch,
                )
        except BackendError as exc:
            logger.warning(
                "Hangup CallLog update failed org_id={} call_id={} sid={}: {}",
                org_id,
                query_call_id or "n/a",
                webhook.provider_call_sid or "n/a",
                exc,
            )
        else:
            if call_response and query_call_id:
                try:
                    await backend_client.notify_campaign_call_status(
                        org_id,
                        query_call_id,
                        call_response,
                    )
                except BackendError as exc:
                    logger.warning(
                        "Campaign status notify failed call_id={}: {}",
                        query_call_id,
                        exc,
                    )
        return Response(status_code=200)

    call_id = query_call_id
    provider = ""

    try:
        agent = await backend_client.get_agent(agent_id, org_id)
        if agent_category(agent) != "telephony":
            return PlainTextResponse(
                "Agent is not a telephony agent",
                status_code=400,
            )
        provider = telephony_provider(agent)

        if not call_id:
            sid = webhook.provider_call_sid
            if sid:
                result = await backend_client.create_inbound_call(
                    org_id,
                    agent_id,
                    provider_call_sid=sid,
                    from_number=webhook.from_number,
                    to_number=webhook.to_number,
                )
                call_id = str(result.get("call_id") or "") or None
                logger.info(
                    "Registered inbound call call_id={} provider_call_sid={}",
                    call_id,
                    sid,
                )
            else:
                logger.warning(
                    "Inbound answer missing provider_call_sid org_id={} agent_id={}",
                    org_id,
                    agent_id,
                )
    except AgentRoutingError as exc:
        return PlainTextResponse(str(exc), status_code=400)
    except BackendError as exc:
        logger.warning(
            "Answer webhook backend error org_id={} agent_id={}: {}",
            org_id,
            agent_id,
            exc,
        )
        return PlainTextResponse(str(exc), status_code=502)

    websocket_url = _websocket_url_for_agent(org_id, agent_id, call_id)
    xml = build_answer_stream_xml(
        provider,
        websocket_url,
        sample_rate=telephony_sample_rate(),
    )
    logger.info(
        "Answer XML org_id={} agent_id={} call_id={} event={} provider={} ws={}",
        org_id,
        agent_id,
        call_id or "n/a",
        webhook.event or "n/a",
        provider,
        websocket_url,
    )
    return Response(content=xml, media_type="application/xml")
