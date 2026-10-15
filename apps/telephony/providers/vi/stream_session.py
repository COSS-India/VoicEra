"""VI Voice Streaming session logic (injected runtime deps).

Kept in the VI provider package so runtime routes stay thin wiring only.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from loguru import logger
from starlette.websockets import WebSocket, WebSocketDisconnect

from .auth_helpers import phone_lookup_candidates, resolve_vi_agent_id

VI_START_TIMEOUT_SECS = 15.0
VI_START_MAX_MESSAGES = 20

GetAgentFn = Callable[[str, str], Awaitable[dict[str, Any]]]
GetAgentByPhoneFn = Callable[[str], Awaitable[dict[str, Any]]]
CreateInboundCallFn = Callable[..., Awaitable[dict[str, Any]]]
RunBotFn = Callable[..., Awaitable[None]]
AgentCategoryFn = Callable[[dict[str, Any]], str]
TelephonyProviderFn = Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class ViStreamDeps:
    """Runtime-injected collaborators (avoids importing apps.runtime here)."""

    get_agent: GetAgentFn
    get_agent_by_phone: GetAgentByPhoneFn
    create_inbound_call: CreateInboundCallFn
    run_bot: RunBotFn
    agent_category: AgentCategoryFn
    telephony_provider: TelephonyProviderFn
    backend_error_type: type[BaseException]


async def read_vi_start_message(websocket: WebSocket) -> tuple[dict, str, str]:
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


def _org_id_from_start(start_info: dict[str, Any]) -> str:
    """Optional org_id from start.custom_parameters (no process env)."""
    custom = (
        start_info.get("custom_parameters")
        or start_info.get("customParameters")
        or {}
    )
    if not isinstance(custom, dict):
        return ""
    for key in ("org_id", "orgId", "organisation_id"):
        value = custom.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


async def resolve_agent_full(
    deps: ViStreamDeps,
    path_agent_id: Optional[str],
    start_info: dict[str, Any],
) -> tuple[Optional[dict[str, Any]], str]:
    """Resolve agent via path → custom_parameters → DNI/CLI by-phone.

    Org for ``get_agent`` comes from a DNI/CLI phone match or optional
    ``org_id`` in ``custom_parameters`` — never from process environment.
    """

    async def _by_phone(phone: str) -> Optional[dict[str, Any]]:
        for candidate in phone_lookup_candidates(phone):
            try:
                return await deps.get_agent_by_phone(candidate)
            except deps.backend_error_type:
                continue
        return None

    async def _load(agent_id: str, org_id: str) -> Optional[dict[str, Any]]:
        try:
            return await deps.get_agent(agent_id, org_id)
        except deps.backend_error_type:
            return None

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
            org_id = _org_id_from_start(start_info)
        if org_id:
            loaded = await _load(agent_id, org_id)
            if loaded:
                return loaded, source
        if dni_agent and str(dni_agent.get("agent_id")) == agent_id:
            return dni_agent, source
        logger.warning(
            "VI could not load agent_id={} (need DNI/CLI match for org_id "
            "or org_id in custom_parameters)",
            agent_id,
        )

    if dni_agent:
        logger.info(
            "VI routed agent={} via {}",
            dni_agent.get("agent_id"),
            dni_source,
        )
        return dni_agent, dni_source

    return None, ""


async def ensure_call_log(
    deps: ViStreamDeps,
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
        created = await deps.create_inbound_call(
            org_id,
            agent_id,
            provider_call_sid=call_sid,
            from_number=cli or "unknown",
            to_number=dni or "unknown",
        )
        return str(created.get("call_id") or "") or None
    except deps.backend_error_type as exc:
        logger.warning("VI create_inbound_call failed: {}", exc)
        return None


def integration_info(voice_server_base_url: str) -> dict[str, Any]:
    """Portal WSS URL hints for operators."""
    base = (voice_server_base_url or "").rstrip("/")
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


async def run_vi_stream_session(
    websocket: WebSocket,
    deps: ViStreamDeps,
    *,
    path_agent_id: Optional[str] = None,
) -> None:
    """Full VI media session after the WebSocket is accepted by the route."""
    await websocket.accept()
    logger.info("VI WebSocket connected (path agent={})", path_agent_id or "-")

    call_sid: str | None = None
    stream_sid: str | None = None

    try:
        start_data, call_sid, stream_sid = await read_vi_start_message(websocket)
        start_info = start_data.get("start", {}) or {}

        agent, route_source = await resolve_agent_full(deps, path_agent_id, start_info)
        if not agent:
            logger.error(
                "VI stream has no resolvable agent "
                "(path/custom_parameters + org, or dni/cli Numbers lookup failed)"
            )
            await websocket.close(code=1008, reason="Missing agent")
            return

        org_id = str(agent.get("org_id") or "").strip()
        agent_id = str(agent.get("agent_id") or "").strip()
        if not org_id or not agent_id:
            logger.error("VI agent document missing org_id/agent_id")
            await websocket.close(code=1008, reason="Invalid agent")
            return

        if deps.agent_category(agent) != "telephony":
            logger.error("VI agent {} is not a telephony agent", agent_id)
            await websocket.close(code=1008, reason="Not telephony agent")
            return

        provider = deps.telephony_provider(agent) or "vi"
        if provider != "vi":
            logger.warning(
                "VI stream agent {} has telephony.provider={!r}; running as vi",
                agent_id,
                provider,
            )

        logger.info(
            "VI agent resolution: agent_id={} org_id={} source={}",
            agent_id,
            org_id,
            route_source,
        )

        cli = str(start_info.get("cli") or "unknown")
        dni = str(start_info.get("dni") or "unknown")
        call_id = await ensure_call_log(
            deps, agent, call_sid=call_sid, cli=cli, dni=dni
        )

        logger.info(
            "VI call started: agent={} call_id={} room_id={} cli={} dni={}",
            agent_id,
            call_sid,
            stream_sid,
            cli,
            dni,
        )

        await deps.run_bot(
            websocket,
            org_id=org_id,
            provider="vi",
            stream_sid=stream_sid,
            call_sid=call_sid,
            call_id=call_id,
            agent=agent,
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
