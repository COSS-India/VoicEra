"""Pipeline event handler registration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from apps.runtime.services.pipecat.config import PipelineConfig
from apps.runtime.services.pipecat.events.logging import register_turn_logging_handlers
from apps.runtime.services.pipecat.events.recording import register_recording_handlers
from apps.runtime.services.pipecat.events.transport import register_transport_handlers
from apps.runtime.services.pipecat.hold import HoldMessageHandler, register_hold_handlers
from apps.runtime.services.pipecat.idle import (
    UserOnlineDetectionHandler,
    register_idle_handlers,
)
from apps.runtime.services.storage.transcript import register_transcript_file_logging

if TYPE_CHECKING:
    from apps.runtime.services.pipecat.factory import PipelineComponents


def register_all_handlers(
    components: PipelineComponents,
    *,
    config: PipelineConfig,
    greeting: str,
    session_label: str,
    hold_handler: HoldMessageHandler | None,
    idle_handler: UserOnlineDetectionHandler | None,
    org_id: str,
    call_id: str | None,
) -> None:
    if call_id:
        components.transcript_writer = register_transcript_file_logging(
            components.user_aggregator,
            components.assistant_aggregator,
            org_id=org_id,
            call_id=call_id,
        )
    register_idle_handlers(
        components.user_aggregator,
        online_detection_enabled=config.online_detection_enabled,
        idle_handler=idle_handler,
        closing_message=config.online_detection_closing_message,
    )
    register_hold_handlers(
        components.user_aggregator,
        components.llm,
        hold_handler,
        idle_handler=idle_handler,
    )
    register_turn_logging_handlers(
        components.user_aggregator,
        components.assistant_aggregator,
        session_label=session_label,
    )
    register_recording_handlers(
        components.audiobuffer,
        org_id=org_id,
        call_id=call_id,
    )
    register_transport_handlers(
        components.transport,
        components.worker,
        session_label=session_label,
        greeting=greeting,
        hold_handler=hold_handler,
    )
