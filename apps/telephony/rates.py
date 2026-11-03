"""Optional per-provider telephony pipeline sample-rate resolution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.telephony.registry import get_pipeline_rate_resolver

__all__ = ["PipelineRates", "resolve_pipeline_rates"]


@dataclass(frozen=True)
class PipelineRates:
    """Wire vs internal pipeline sample rates for a telephony call.

    Recording uses the pipeline rate via Pipecat's ``AudioBufferProcessor``
    after ``transport.output()`` — no separate recording rate.
    """

    wire_rate: int
    pipeline_rate: int


def resolve_pipeline_rates(provider: str, tts: Any) -> PipelineRates | None:
    """Return provider-specific rates, or ``None`` to use the runtime default path."""
    resolver = get_pipeline_rate_resolver(provider)
    if resolver is None:
        return None
    return resolver(tts)
