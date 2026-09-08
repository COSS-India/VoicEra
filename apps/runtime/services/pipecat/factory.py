"""Pipecat pipeline component construction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)
from pipecat.turns.user_mute import MuteUntilFirstBotCompleteUserMuteStrategy
from pipecat.turns.user_start import MinWordsUserTurnStartStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from starlette.websockets import WebSocket

from apps.runtime.services.knowledge.setup import configure_knowledge_base
from apps.runtime.services.pipecat.call_ending import configure_call_ending
from apps.runtime.services.pipecat.config import PipelineConfig
from apps.runtime.services.pipecat.metrics.writer import CallMetricsWriter
from apps.runtime.services.storage.transcript import TranscriptWriter


@dataclass
class PipelineComponents:
    transport: FastAPIWebsocketTransport
    pipeline: Pipeline
    worker: PipelineWorker
    user_aggregator: Any
    assistant_aggregator: Any
    llm: Any
    audiobuffer: AudioBufferProcessor
    context: LLMContext
    transcript_writer: TranscriptWriter | None = None
    metrics_writer: CallMetricsWriter | None = None


def build_pipeline_components(
    *,
    websocket: WebSocket,
    serializer: Any,
    sample_rate: int,
    stt: Any,
    tts: Any,
    llm: Any,
    system_prompt: str,
    config: PipelineConfig,
    agent: dict[str, Any],
    org_id: str,
    behaviour: dict[str, Any],
) -> PipelineComponents:
    vad_analyzer = SileroVADAnalyzer(
        sample_rate=sample_rate,
        params=VADParams(
            stop_secs=0.4,
            min_volume=0.5,
            confidence=0.3,
            start_secs=0.1,
        ),
    )

    audiobuffer = AudioBufferProcessor(
        num_channels=1,
        enable_turn_audio=False,
        auto_start_recording=True,
    )

    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            add_wav_header=False,
            serializer=serializer,
        ),
    )

    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    context = LLMContext(messages)
    user_params = LLMUserAggregatorParams(
        vad_analyzer=vad_analyzer,
        user_idle_timeout=config.user_idle_timeout,
        user_mute_strategies=(
            [MuteUntilFirstBotCompleteUserMuteStrategy()]
            if config.ignore_user_speech_before_greeting
            else []
        ),
    )
    if config.interruption_min_words > 0:
        user_params.user_turn_strategies = UserTurnStrategies(
            start=[
                MinWordsUserTurnStartStrategy(
                    min_words=config.interruption_min_words
                )
            ],
        )
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context, user_params=user_params
    )

    kb_context_processor = configure_knowledge_base(
        agent,
        org_id=org_id,
        context=context,
        aggregators=(user_aggregator, assistant_aggregator),
    )
    configure_call_ending(
        behaviour,
        context=context,
        agent_id=agent.get("agent_id"),
    )

    pipeline_processors = [
        transport.input(),
        stt,
        user_aggregator,
    ]
    if kb_context_processor is not None:
        pipeline_processors.append(kb_context_processor)
    pipeline_processors.extend(
        [
            llm,
            tts,
            transport.output(),
            audiobuffer,
            assistant_aggregator,
        ]
    )

    pipeline = Pipeline(pipeline_processors)

    worker = PipelineWorker(
        pipeline,
        params=PipelineParams(
            audio_in_sample_rate=sample_rate,
            audio_out_sample_rate=sample_rate,
            enable_metrics=True,
            enable_usage_metrics=False,
            send_initial_empty_metrics=False,
        ),
        idle_timeout_secs=None,
        processor_unusable_policy=ProcessorUnusablePolicy.END,
    )

    return PipelineComponents(
        transport=transport,
        pipeline=pipeline,
        worker=worker,
        user_aggregator=user_aggregator,
        assistant_aggregator=assistant_aggregator,
        llm=llm,
        audiobuffer=audiobuffer,
        context=context,
    )
