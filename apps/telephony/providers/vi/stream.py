"""VI WebSocket session orchestration (called from runtime route)."""

from __future__ import annotations

import asyncio
import os
from typing import Any, Awaitable, Callable, Optional

from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from apps.telephony.providers.vi.routing import resolve_vi_agent_id
from apps.telephony.providers.vi.wss_protocol import dni_lookup_candidates, read_vi_start_message

GetAgentByPhone = Callable[[str], Awaitable[dict[str, Any]]]
GetAgent = Callable[[str, str], Awaitable[dict[str, Any]]]
CreateInboundCall = Callable[..., Awaitable[dict[str, Any]]]
RunTelephonyBot = Callable[..., Awaitable[None]]
AgentCategory = Callable[[dict[str, Any]], str]
TelephonyProvider = Callable[[dict[str, Any]], str | None]


async def _resolve_agent_full(
    path_agent_id: Optional[str],
    start_info: dict[str, Any],
    *,
    get_agent_by_phone: GetAgentByPhone,
    get_agent: GetAgent,
) -> tuple[Optional[dict[str, Any]], str]:
    dni_agent: Optional[dict[str, Any]] = None
    dni_source = ""
    for phone in dni_lookup_candidates(start_info):
        found = await get_agent_by_phone(phone)
        if found and found.get("agent_id"):
            dni_agent = found
            dni_source = f"by-phone:{phone}"
            break

    agent_id = resolve_vi_agent_id(path_agent_id, start_info)
    if agent_id:
        source = "path" if path_agent_id else "custom_parameters"
        org_id = str((dni_agent or {}).get("org_id") or "").strip()
        if not org_id:
            org_id = (os.environ.get("VI_DEFAULT_ORG_ID") or "").strip()
        if org_id:
            loaded = await get_agent(agent_id, org_id)
            if loaded:
                return loaded, source
        if dni_agent and str(dni_agent.get("agent_id")) == agent_id:
            return dni_agent, source

    if dni_agent:
        return dni_agent, dni_source

    default_id = (os.environ.get("VI_DEFAULT_AGENT_ID") or "").strip()
    default_org = (os.environ.get("VI_DEFAULT_ORG_ID") or "").strip()
    if default_id and default_org:
        loaded = await get_agent(default_id, default_org)
        if loaded:
            return loaded, "VI_DEFAULT_AGENT_ID"

    return None, ""


async def handle_session(
    websocket: WebSocket,
    *,
    path_agent_id: Optional[str] = None,
    get_agent_by_phone: GetAgentByPhone,
    get_agent: GetAgent,
    create_inbound_call: CreateInboundCall,
    run_telephony_bot: RunTelephonyBot,
    agent_category: AgentCategory,
    telephony_provider: TelephonyProvider,
) -> None:
    """Accept VI media stream, resolve agent by DNI, run telephony bot."""
    await websocket.accept()
    call_sid: str | None = None

    async def _get_agent_by_phone_safe(phone: str) -> Optional[dict[str, Any]]:
        try:
            return await get_agent_by_phone(phone)
        except Exception:
            return None

    async def _get_agent_safe(agent_id: str, org_id: str) -> Optional[dict[str, Any]]:
        try:
            return await get_agent(agent_id, org_id)
        except Exception:
            return None

    try:
        start_data, call_sid, stream_sid = await read_vi_start_message(websocket)
        start_info = start_data.get("start", {}) or {}

        agent, route_source = await _resolve_agent_full(
            path_agent_id,
            start_info,
            get_agent_by_phone=_get_agent_by_phone_safe,
            get_agent=_get_agent_safe,
        )
        if not agent:
            await websocket.close(code=1008, reason="Missing agent")
            return

        org_id = str(agent.get("org_id") or "").strip()
        agent_id = str(agent.get("agent_id") or "").strip()
        if not org_id or not agent_id:
            await websocket.close(code=1008, reason="Invalid agent")
            return

        if agent_category(agent) != "telephony":
            await websocket.close(code=1008, reason="Not telephony agent")
            return

        provider = telephony_provider(agent) or "vi"
        if provider != "vi":
            provider = "vi"

        logger.info(
            "VI agent resolution: agent_id={} org_id={} source={}",
            agent_id,
            org_id,
            route_source,
        )

        cli = str(start_info.get("cli") or "unknown")
        dni = str(start_info.get("dni") or "unknown")
        call_id: str | None = None
        try:
            created = await create_inbound_call(
                org_id,
                agent_id,
                provider_call_sid=call_sid,
                from_number=cli,
                to_number=dni,
            )
            call_id = str(created.get("call_id") or "") or None
        except Exception as exc:
            logger.warning("VI create_inbound_call failed: {}", exc)

        await run_telephony_bot(
            websocket,
            org_id=org_id,
            provider=provider,
            stream_sid=stream_sid,
            call_sid=call_sid,
            call_id=call_id,
            agent=agent,
            custom_variables=None,
        )

    except (asyncio.TimeoutError, TimeoutError):
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
