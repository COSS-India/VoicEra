"""Pure LID switch policy — no I/O."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from apps.runtime.services.language_switch.lid.config import PROBE_LANGUAGE_CODES
from apps.runtime.services.language_switch.lid.types import LidDecision, LidResult


@dataclass
class LidPolicy:
    """Decide whether a LID result should switch the call language."""

    allowed_languages: frozenset[str]
    min_confidence: float = 0.7
    min_audio_sec: float = 1.8
    cooldown_sec: float = 3.0
    active_language: str = ""
    _last_switch_at: float = field(default=0.0, repr=False)

    def set_active_language(self, language: str) -> None:
        self.active_language = (language or "").strip()

    def note_switch(self, language: str, *, at: float | None = None) -> None:
        self.active_language = (language or "").strip()
        self._last_switch_at = time.monotonic() if at is None else at

    def decide(
        self,
        result: LidResult,
        *,
        buffered_audio_sec: float,
        now: float | None = None,
    ) -> LidDecision:
        """Return switch/stay for one identify result."""
        mono = time.monotonic() if now is None else now
        code = (result.language_code or "").strip().lower().split("-")[0]
        conf = float(result.confidence or 0.0)
        active = (self.active_language or "").strip().lower().split("-")[0]

        if buffered_audio_sec < self.min_audio_sec:
            return LidDecision(
                outcome="stay",
                language=code or None,
                reason="short_audio",
                confidence=conf,
            )
        if not code:
            return LidDecision(outcome="stay", reason="missing_language", confidence=conf)
        if code not in PROBE_LANGUAGE_CODES:
            return LidDecision(
                outcome="stay",
                language=code,
                reason="not_in_probe",
                confidence=conf,
            )
        if code not in self.allowed_languages:
            return LidDecision(
                outcome="stay",
                language=code,
                reason="unsupported_language",
                confidence=conf,
            )
        if code == active:
            return LidDecision(
                outcome="stay",
                language=code,
                reason="already_active",
                confidence=conf,
            )
        if conf < self.min_confidence:
            return LidDecision(
                outcome="stay",
                language=code,
                reason="low_confidence",
                confidence=conf,
            )
        if self._last_switch_at and (mono - self._last_switch_at) < self.cooldown_sec:
            return LidDecision(
                outcome="stay",
                language=code,
                reason="cooldown",
                confidence=conf,
            )
        return LidDecision(
            outcome="switch",
            language=code,
            reason="lid_switch",
            confidence=conf,
        )
