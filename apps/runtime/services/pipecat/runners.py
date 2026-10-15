"""Public entrypoints for telephony and browser WebSocket Pipecat pipelines."""

from __future__ import annotations

from typing import Any

from loguru import logger
from pipecat.serializers.protobuf import ProtobufFrameSerializer
from starlette.websockets import WebSocket

from apps.runtime.constants import telephony_sample_rate, websocket_sample_rate
from apps.runtime.services.ai_service_factory import build_ai_services
from apps.runtime.services.pipecat.pipeline import run_pipeline
from apps.telephony.rates import resolve_pipeline_rates
from apps.telephony.registry import get_pipeline_rate_resolver
from apps.telephony.serializers import create_frame_serializer


async def run_telephony_bot(
    websocket: WebSocket,
    *,
    org_id: str,
    provider: str,
    stream_sid: str,
    call_sid: str,
    call_id: str | None,
    agent: dict[str, Any],
    custom_variables: dict[str, Any] | None = None,
    sample_rate: int | None = None,
) -> None:
    """Run the Pipecat pipeline for a telephony media stream."""
    if get_pipeline_rate_resolver(provider) is not None:
        stt, tts, llm = await build_ai_services(agent)
        rates = resolve_pipeline_rates(provider, tts)
        assert rates is not None
        logger.info(
            "Telephony sample rates ({}): wire={}Hz pipeline={}Hz recording={}Hz tts={}",
            provider,
            rates.wire_rate,
            rates.pipeline_rate,
            rates.recording_rate,
            type(tts).__name__,
        )
        serializer = create_frame_serializer(
            provider,
            stream_sid=stream_sid,
            call_sid=call_sid,
            sample_rate=rates.pipeline_rate,
            websocket=websocket,
        )
        await run_pipeline(
            websocket,
            org_id=org_id,
            agent=agent,
            serializer=serializer,
            sample_rate=rates.pipeline_rate,
            call_id=call_id,
            custom_variables=custom_variables,
            session_label=f"call_sid={call_sid}",
            finalize_call=True,
            stt=stt,
            tts=tts,
            llm=llm,
            recording_sample_rate=rates.recording_rate,
        )
        return

    rate = sample_rate if sample_rate is not None else telephony_sample_rate()
    serializer = create_frame_serializer(
        provider,
        stream_sid=stream_sid,
        call_sid=call_sid,
        sample_rate=rate,
        websocket=websocket,
    )
    await run_pipeline(
        websocket,
        org_id=org_id,
        agent=agent,
        serializer=serializer,
        sample_rate=rate,
        call_id=call_id,
        custom_variables=custom_variables,
        session_label=f"call_sid={call_sid}",
        finalize_call=True,
    )


async def run_websocket_bot(
    websocket: WebSocket,
    *,
    org_id: str,
    agent: dict[str, Any],
    call_id: str | None = None,
    custom_variables: dict[str, Any] | None = None,
) -> None:
    """Run the Pipecat pipeline for a browser WebSocket client (RTVI/protobuf)."""
    sample_rate = websocket_sample_rate()
    serializer = ProtobufFrameSerializer()
    session_label = (
        f"call_id={call_id}" if call_id else f"agent_id={agent.get('agent_id')}"
    )
    await run_pipeline(
        websocket,
        org_id=org_id,
        agent=agent,
        serializer=serializer,
        sample_rate=sample_rate,
        call_id=call_id,
        custom_variables=custom_variables,
        session_label=session_label,
        finalize_call=bool(call_id),
    )
