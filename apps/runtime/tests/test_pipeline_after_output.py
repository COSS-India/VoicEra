"""LLM-requested processors after transport output, bare or behind a switcher."""

from __future__ import annotations

from pipecat.pipeline.service_switcher import ServiceSwitcher, ServiceSwitcherStrategyManual
from pipecat.processors.frame_processor import FrameProcessor

from apps.runtime.services.pipecat.factory import _processors_after_output


class _LLMWithHangup(FrameProcessor):
    def __init__(self) -> None:
        super().__init__()
        self.hangup = FrameProcessor()

    def pipeline_processors_after_output(self) -> list[FrameProcessor]:
        return [self.hangup]


def test_a_bare_llm_contributes_its_processors():
    llm = _LLMWithHangup()
    assert _processors_after_output(llm) == [llm.hangup]


def test_a_plain_llm_contributes_nothing():
    assert _processors_after_output(FrameProcessor()) == []


def test_every_switcher_member_contributes():
    """A Kenpath LLM on a secondary language still gets its hangup processor."""
    plain, kenpath = FrameProcessor(), _LLMWithHangup()
    switcher = ServiceSwitcher(
        [plain, kenpath], strategy_type=ServiceSwitcherStrategyManual
    )
    assert _processors_after_output(switcher) == [kenpath.hangup]
