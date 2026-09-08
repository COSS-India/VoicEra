"""Agent WebSocket endpoint — telephony and browser media streams."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from apps.runtime.services.agent_routing import (
    AgentRoutingError,
    agent_category,
    telephony_provider,
)
from apps.runtime.services.backend import BackendError, backend_client
from apps.runtime.services.pipecat.audio import resolve_custom_variables
from apps.runtime.services.pipecat.runners import run_telephony_bot, run_websocket_bot
from apps.telephony import parse_stream_start

router = APIRouter()


@router.websocket("/agent/{org_id}/{agent_id}")
async def agent_websocket(websocket: WebSocket, org_id: str, agent_id: str) -> None:
    """Accept telephony or browser media stream and run the Pipecat pipeline."""
    await websocket.accept()
    call_id = (websocket.query_params.get("call_id") or "").strip() or None
    logger.info(
        "WebSocket accepted org_id={} agent_id={} call_id={}",
        org_id,
        agent_id,
        call_id or "n/a",
    )

    call_sid: str | None = None
    stream_sid: str | None = None

    try:
        agent = await backend_client.get_agent(agent_id, org_id)
        category = agent_category(agent)
        logger.info(
            "Loaded agent name={!r} category={} telephony={}",
            agent.get("name"),
            category,
            (agent.get("telephony") or {}).get("provider"),
        )

        if category == "websocket":
            call_log: dict[str, Any] | None = None
            if call_id:
                try:
                    call_log = await backend_client.get_call(call_id, org_id)
                    if str(call_log.get("call_type") or "") != "web":
                        logger.warning(
                            "Ignoring call_id={} — expected call_type=web, got {}",
                            call_id,
                            call_log.get("call_type"),
                        )
                        call_id = None
                        call_log = None
                    elif str(call_log.get("agent_id") or "") != agent_id:
                        logger.warning(
                            "Ignoring call_id={} — agent_id mismatch",
                            call_id,
                        )
                        call_id = None
                        call_log = None
                except BackendError as exc:
                    logger.warning(
                        "Failed to load web call log call_id={} org_id={}: {}",
                        call_id,
                        org_id,
                        exc,
                    )
                    call_id = None
                    call_log = None

            if not call_id:
                try:
                    result = await backend_client.create_web_call(org_id, agent_id)
                    call_id = str(result.get("call_id") or "") or None
                    logger.info("Registered web call call_id={}", call_id)
                    if call_id:
                        try:
                            call_log = await backend_client.get_call(call_id, org_id)
                        except BackendError as exc:
                            logger.warning(
                                "Failed to load new web call log call_id={}: {}",
                                call_id,
                                exc,
                            )
                except BackendError as exc:
                    logger.warning(
                        "Web call registration failed org_id={} agent_id={}: {}",
                        org_id,
                        agent_id,
                        exc,
                    )

            custom_variables = resolve_custom_variables(agent, call_log)
            await run_websocket_bot(
                websocket,
                org_id=org_id,
                agent=agent,
                call_id=call_id,
                custom_variables=custom_variables,
            )
            return

        provider = telephony_provider(agent)

        first = await websocket.receive_text()
        data: dict[str, Any] = json.loads(first)
        if data.get("event") != "start":
            logger.warning(
                "Expected start event, got {!r} — closing",
                data.get("event"),
            )
            await websocket.close(code=1008, reason="Expected start event")
            return

        start_info = data.get("start") or {}
        stream_meta = parse_stream_start(start_info)
        call_sid = (
            stream_meta.get("provider_call_sid")
            or start_info.get("callSid")
            or start_info.get("callId")
            or start_info.get("call_uuid")
            or "unknown"
        )
        stream_sid = (
            start_info.get("streamSid")
            or start_info.get("streamId")
            or "unknown"
        )
        logger.info(
            "Call start call_sid={} stream_sid={}",
            call_sid,
            stream_sid,
        )

        if not call_id and call_sid and call_sid != "unknown":
            try:
                result = await backend_client.create_inbound_call(
                    org_id,
                    agent_id,
                    provider_call_sid=str(call_sid),
                    from_number="unknown",
                    to_number="unknown",
                )
                call_id = str(result.get("call_id") or "") or None
                logger.info(
                    "Registered inbound call from WebSocket call_id={} provider_call_sid={}",
                    call_id,
                    call_sid,
                )
            except BackendError as exc:
                logger.warning(
                    "WebSocket inbound registration failed org_id={} call_sid={}: {}",
                    org_id,
                    call_sid,
                    exc,
                )

        call_log: dict[str, Any] | None = None
        if call_id:
            try:
                call_log = await backend_client.get_call(call_id, org_id)
                logger.info(
                    "Call context call_id={} call_type={} custom_variables={}",
                    call_id,
                    call_log.get("call_type"),
                    call_log.get("custom_variables"),
                )
            except BackendError as exc:
                logger.warning(
                    "Failed to load call log call_id={} org_id={}: {}",
                    call_id,
                    org_id,
                    exc,
                )

        custom_variables = resolve_custom_variables(agent, call_log)

        await run_telephony_bot(
            websocket,
            org_id=org_id,
            provider=provider,
            stream_sid=str(stream_sid),
            call_sid=str(call_sid),
            call_id=call_id,
            agent=agent,
            custom_variables=custom_variables,
        )
    except AgentRoutingError as exc:
        logger.warning("Agent routing error agent_id={}: {}", agent_id, exc)
        try:
            await websocket.close(code=1008, reason=str(exc)[:120])
        except Exception:
            pass
    except BackendError as exc:
        logger.error("Backend error for agent {}: {}", agent_id, exc)
        try:
            await websocket.close(code=1011, reason=str(exc)[:120])
        except Exception:
            pass
    except WebSocketDisconnect:
        logger.info(
            "WebSocket disconnected agent_id={} call_sid={}",
            agent_id,
            call_sid,
        )
    except Exception:
        logger.exception(
            "WebSocket pipeline failed agent_id={} call_sid={}",
            agent_id,
            call_sid,
        )
        try:
            await websocket.close(code=1011, reason="Pipeline error")
        except Exception:
            pass
    finally:
        logger.info(
            "WebSocket closed agent_id={} call_sid={}",
            agent_id,
            call_sid,
        )
