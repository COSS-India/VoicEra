"""Core Pipecat pipeline orchestration."""

from __future__ import annotations

from typing import Any

from starlette.websockets import WebSocket

from apps.runtime.services.ai_service_factory import build_ai_services
from apps.runtime.services.pipecat.audio import prompts
from apps.runtime.services.pipecat.config import pipeline_config_from_behaviour
from apps.runtime.services.pipecat.events import register_all_handlers
from apps.runtime.services.pipecat.factory import build_pipeline_components
from apps.runtime.services.pipecat.hold import hold_from_behaviour
from apps.runtime.services.pipecat.idle import UserOnlineDetectionHandler
from apps.runtime.services.pipecat.lifecycle import SessionContext, run_with_lifecycle
from apps.runtime.services.pipecat.metrics import CallMetricsWriter, register_call_metrics


async def run_pipeline(
    websocket: WebSocket,
    *,
    org_id: str,
    agent: dict[str, Any],
    serializer: Any,
    sample_rate: int,
    call_id: str | None = None,
    custom_variables: dict[str, Any] | None = None,
    session_label: str = "session",
    finalize_call: bool = False,
) -> None:
    """Shared Pipecat pipeline for telephony and browser WebSocket agents."""
    stt, tts, llm = await build_ai_services(agent)
    if call_id and hasattr(llm, "set_call_id"):
        llm.set_call_id(call_id)
    system_prompt, greeting = prompts(agent, custom_variables=custom_variables)
    behaviour = (agent.get("config") or {}).get("behaviour") or {}
    config = pipeline_config_from_behaviour(behaviour)
    hold_handler = hold_from_behaviour(behaviour, tts)

    idle_handler: UserOnlineDetectionHandler | None = None
    if config.online_detection_enabled:
        idle_handler = UserOnlineDetectionHandler(
            max_repeats=config.online_detection_repeats,
            idle_message=config.online_detection_message,
            closing_message=config.online_detection_closing_message,
        )

    components = build_pipeline_components(
        websocket=websocket,
        serializer=serializer,
        sample_rate=sample_rate,
        stt=stt,
        tts=tts,
        llm=llm,
        system_prompt=system_prompt,
        config=config,
        agent=agent,
        org_id=org_id,
        behaviour=behaviour,
    )

    if call_id:
        metrics_writer = CallMetricsWriter(
            org_id=org_id,
            call_id=call_id,
            session_label=session_label,
            processor_stages={
                stt.name: "stt",
                tts.name: "tts",
                llm.name: "llm",
            },
        )
        register_call_metrics(components.worker, metrics_writer)
        components.metrics_writer = metrics_writer

    register_all_handlers(
        components,
        config=config,
        greeting=greeting,
        session_label=session_label,
        hold_handler=hold_handler,
        idle_handler=idle_handler,
        org_id=org_id,
        call_id=call_id,
    )

    ctx = SessionContext(
        org_id=org_id,
        call_id=call_id,
        session_label=session_label,
        finalize_call=finalize_call,
        agent_id=agent.get("agent_id"),
        sample_rate=sample_rate,
        transcript_writer=components.transcript_writer,
        metrics_writer=components.metrics_writer,
    )
    await run_with_lifecycle(components.worker, ctx)
