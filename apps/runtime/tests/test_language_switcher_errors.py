"""A dead active service behind a language switcher still ends the call."""

from __future__ import annotations

import asyncio
from typing import Any

from pipecat.frames.frames import ErrorFrame, Frame, StartFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker, ProcessorUnusablePolicy
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.utils.errors import ErrorCategory
from pipecat.workers.runner import WorkerRunner

from apps.runtime.services.language_switch.routes import LanguageRoute
from apps.runtime.services.language_switch.switcher import ModelServiceSwitcher


class _Service(FrameProcessor):
    def __init__(self, name: str, *, fail_on_start: bool = False) -> None:
        super().__init__(name=name)
        self._fail_on_start = fail_on_start

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)
        if isinstance(frame, StartFrame) and self._fail_on_start:
            await self.push_error("key rejected", category=ErrorCategory.AUTHENTICATION)


def _run(services: list[_Service]) -> list[ErrorFrame]:
    switcher = ModelServiceSwitcher(
        kind="stt",
        services=services,
        routes={
            f"l{i}": LanguageRoute(service=s, settings_delta=None)
            for i, s in enumerate(services)
        },
        primary_language="l0",
    )
    worker = PipelineWorker(
        Pipeline([switcher]),
        params=PipelineParams(),
        idle_timeout_secs=None,
        processor_unusable_policy=ProcessorUnusablePolicy.END,
    )
    errors: list[ErrorFrame] = []

    @worker.event_handler("on_pipeline_error")
    async def _on_error(_worker: Any, frame: ErrorFrame) -> None:
        errors.append(frame)

    async def main() -> None:
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(worker)
        # Ends on its own only if the unusable policy fires.
        await asyncio.wait_for(runner.run(), timeout=5)

    asyncio.run(main())
    return errors


def test_the_failed_service_is_reported_with_its_own_category():
    """Two languages on two providers: the primary's key is rejected."""
    active = _Service("SarvamSTTService#0", fail_on_start=True)
    errors = _run([active, _Service("DeepgramSTTService#0")])
    assert len(errors) == 1
    assert errors[0].processor is active
    assert errors[0].category is ErrorCategory.AUTHENTICATION
    assert not errors[0].processor.is_usable


def test_a_single_service_switcher_reports_the_service_too():
    active = _Service("SarvamSTTService#0", fail_on_start=True)
    errors = _run([active])
    assert [e.processor for e in errors] == [active]
