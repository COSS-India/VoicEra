"""Types for Nemotron LID results and switch decisions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

LidOutcome = Literal["switch", "stay"]


@dataclass(frozen=True)
class LidResult:
    """Response from the Nemotron LID identify endpoint."""

    language_code: str
    confidence: float
    duration_sec: float = 0.0
    detected_language: str | None = None
    probabilities: dict[str, float] | None = None


@dataclass(frozen=True)
class LidDecision:
    """Policy outcome for one identify result."""

    outcome: LidOutcome
    language: str | None = None
    reason: str = ""
    confidence: float | None = None
