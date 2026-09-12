"""Vodafone Idea (VI) direct WebSocket media routes.

VI DIY flows open WSS to these endpoints after answer — there is no ``/answer``
Stream XML hop (unlike Vobiz/Plivo).
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from apps.runtime.services.agent_routing import agent_category, telephony_provider
from apps.runtime.services.backend import BackendError, backend_client
from apps.runtime.services.pipecat.runners import run_telephony_bot
from apps.telephony.providers.vi.obd_client import resolve_vi_agent_id
from apps.telephony.providers.vi.serializers import VI_SAMPLE_RATE

router = APIRouter(tags=["vi-telephony"])

VI_START_TIMEOUT_SECS = 15.0
VI_START_MAX_MESSAGES = 20


async def _read_vi_start_message(websocket: WebSocket) -> tuple[dict, str, str]:
    """Read VI WebSocket messages until the start event is received."""
    for _ in range(VI_START_MAX_MESSAGES):
        message = await asyncio.wait_for(
            websocket.receive_text(), timeout=VI_START_TIMEOUT_SECS
        )
        data = json.loads(message)
        event = data.get("event")
        if event == "connected":
            logger.info("VI WebSocket connected event received")
            continue
        if event == "start":
            start_info = data.get("start", {}) or {}
            call_sid = (
                start_info.get("call_id")
                or data.get("call_id")
                or start_info.get("callSid")
                or "unknown"
            )
            stream_sid = (
                data.get("room_id")
                or start_info.get("room_id")
                or start_info.get("streamSid")
                or "unknown"
            )
            return data, str(call_sid), str(stream_sid)
        logger.warning("VI WebSocket expected connected/start, got event={}", event)
    raise TimeoutError("VI start event not received")


async def _resolve_agent_full(
    path_agent_id: Optional[str], start_info: dict[str, Any]
) -> tuple[Optional[dict[str, Any]], str]:
    """path → custom_parameters → DNI/CLI by-phone → VI_DEFAULT_AGENT_ID."""

    async def _by_phone(phone: str) -> Optional[dict[str, Any]]:
        try:
            return await backend_client.get_agent_by_phone(phone)
        except BackendError:
            return None

    async def _load(agent_id: str, org_id: str) -> Optional[dict[str, Any]]:
        try:
            return await backend_client.get_agent(agent_id, org_id)
        except BackendError:
            return None

    # Discover org via DNI/CLI when possible (needed for path/custom/default loads).
    dni_agent: Optional[dict[str, Any]] = None
    dni_source = ""
    for field in ("dni", "DNI", "cli", "CLI"):
        raw = start_info.get(field)
        if not raw:
            continue
        found = await _by_phone(str(raw).strip())
        if found and found.get("agent_id"):
            dni_agent = found
            dni_source = f"{field.lower()}:{raw}"
            break

    agent_id = resolve_vi_agent_id(path_agent_id, start_info)
    if agent_id:
        source = "path" if path_agent_id else "custom_parameters"
        org_id = str((dni_agent or {}).get("org_id") or "").strip()
        if not org_id:
            org_id = (os.environ.get("VI_DEFAULT_ORG_ID") or "").strip()
        if org_id:
            loaded = await _load(agent_id, org_id)
            if loaded:
                return loaded, source
        if dni_agent and str(dni_agent.get("agent_id")) == agent_id:
            return dni_agent, source
        logger.warning(
            "VI could not load agent_id={} (need matching DNI org or VI_DEFAULT_ORG_ID)",
            agent_id,
        )

    if dni_agent:
        logger.info(
            "VI routed agent={} via {}",
            dni_agent.get("agent_id"),
            dni_source,
        )
        return dni_agent, dni_source

    default_id = (os.environ.get("VI_DEFAULT_AGENT_ID") or "").strip()
    default_org = (os.environ.get("VI_DEFAULT_ORG_ID") or "").strip()
    if default_id and default_org:
        loaded = await _load(default_id, default_org)
        if loaded:
            logger.info("VI routed agent={} via VI_DEFAULT_AGENT_ID", default_id)
            return loaded, "VI_DEFAULT_AGENT_ID"

    return None, ""


async def _ensure_call_log(
    agent: dict[str, Any],
    *,
    call_sid: str,
    cli: str,
    dni: str,
) -> str | None:
    """Register inbound CallLog for the VI stream; return VoicERA call_id."""
    org_id = str(agent.get("org_id") or "").strip()
    agent_id = str(agent.get("agent_id") or "").strip()
    if not org_id or not agent_id:
        return None
    try:
        created = await backend_client.create_inbound_call(
            org_id,
            agent_id,
            provider_call_sid=call_sid,
            from_number=cli or "unknown",
            to_number=dni or "unknown",
        )
        return str(created.get("call_id") or "") or None
    except BackendError as exc:
        logger.warning("VI create_inbound_call failed: {}", exc)
        return None


async def _run_vi_session(
    websocket: WebSocket, path_agent_id: Optional[str] = None
) -> None:
    await websocket.accept()
    logger.info("VI WebSocket connected (path agent={})", path_agent_id or "-")

    call_sid: str | None = None
    stream_sid: str | None = None

    try:
        start_data, call_sid, stream_sid = await _read_vi_start_message(websocket)
        start_info = start_data.get("start", {}) or {}

        agent, route_source = await _resolve_agent_full(path_agent_id, start_info)
        if not agent:
            logger.error(
                "VI stream has no resolvable agent "
                "(path, custom_parameters, dni/cli lookup, VI_DEFAULT_* all failed)"
            )
            await websocket.close(code=1008, reason="Missing agent")
            return

        org_id = str(agent.get("org_id") or "").strip()
        agent_id = str(agent.get("agent_id") or "").strip()
        if not org_id or not agent_id:
            logger.error("VI agent document missing org_id/agent_id")
            await websocket.close(code=1008, reason="Invalid agent")
            return

        if agent_category(agent) != "telephony":
            logger.error("VI agent {} is not a telephony agent", agent_id)
            await websocket.close(code=1008, reason="Not telephony agent")
            return

        provider = telephony_provider(agent) or "vi"
        if provider != "vi":
            logger.warning(
                "VI stream agent {} has telephony.provider={!r}; running as vi",
                agent_id,
                provider,
            )
            provider = "vi"

        logger.info(
            "VI agent resolution: agent_id={} org_id={} source={}",
            agent_id,
            org_id,
            route_source,
        )

        cli = str(start_info.get("cli") or "unknown")
        dni = str(start_info.get("dni") or "unknown")
        call_id = await _ensure_call_log(
            agent, call_sid=call_sid, cli=cli, dni=dni
        )

        logger.info(
            "VI call started: agent={} call_id={} room_id={} cli={} dni={}",
            agent_id,
            call_sid,
            stream_sid,
            cli,
            dni,
        )
        logger.info(
            "VI pipeline starting: agent={} org_id={} call_log_id={} provider_call_sid={}",
            agent_id,
            org_id,
            call_id,
            call_sid,
        )

        await run_telephony_bot(
            websocket,
            org_id=org_id,
            provider="vi",
            stream_sid=stream_sid,
            call_sid=call_sid,
            call_id=call_id,
            agent=agent,
            sample_rate=VI_SAMPLE_RATE,
        )
        logger.info(
            "VI pipeline finished: agent={} call_id={} room_id={}",
            agent_id,
            call_sid,
            stream_sid,
        )

    except (asyncio.TimeoutError, TimeoutError):
        logger.error("VI stream did not send a start event in time")
        try:
            await websocket.close(code=1008, reason="No start event")
        except Exception:
            pass
    except WebSocketDisconnect:
        logger.info("VI WebSocket disconnected: call_id={}", call_sid)
    except Exception as exc:
        logger.exception("VI WebSocket error: {}", exc)
        try:
            await websocket.close(code=1011, reason="VI session error")
        except Exception:
            pass
    finally:
        logger.info("VI WebSocket closed: call_id={}", call_sid)


@router.websocket("/vi/stream")
async def vi_stream_websocket(websocket: WebSocket) -> None:
    """Static VI streaming endpoint; agent resolved from DNI / custom params."""
    await _run_vi_session(websocket)


@router.websocket("/vi/agent/{agent_id}")
async def vi_agent_websocket(websocket: WebSocket, agent_id: str) -> None:
    """Legacy VI streaming endpoint with agent id in the URL path."""
    await _run_vi_session(websocket, path_agent_id=agent_id)


@router.get("/vi/integration-info")
async def vi_integration_info() -> dict[str, Any]:
    """Return portal WSS URL hints for operators."""
    base = (os.environ.get("VOICE_SERVER_BASE_URL") or "").rstrip("/")
    if base.startswith("https://"):
        wss = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        wss = "ws://" + base[len("http://") :]
    elif base.startswith("wss://") or base.startswith("ws://"):
        wss = base
    else:
        wss = f"wss://{base}" if base else ""
    return {
        "provider": "vi",
        "websocket_url": f"{wss}/vi/stream" if wss else "/vi/stream",
        "websocket_url_legacy": f"{wss}/vi/agent/{{agent_id}}" if wss else None,
        "protocol": "VI Voice Streaming (bidirectional, 8kHz PCM16, JSON over WSS)",
        "note": "Configure the VI DIY Streaming Object once; route agents by DNI on Numbers.",
    }
