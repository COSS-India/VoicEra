"""Pure language judge: pick the language with the strongest IndicLID evidence.

Evidence model (see the measurements behind it in ``indiclid.py``):

* Kannada, Tamil and Telugu script each identify one language; the vote is that
  language's IndicLID score.
* Devanagari carries votes for Hindi and Marathi only (their IndicLID scores).
  The remaining Devanagari mass (Maithili, Nepali, Sanskrit, ...) is an
  abstain: it covers real Hindi as well as Dravidian speech written in
  Devanagari, so it never becomes a vote. Devanagari is never read as Kannada.
* The main ASR writes in the script of the *active* language, so its
  kn/ta/te votes only restate that language and are ignored. Its hi/mr votes
  are content-based and count. Nemotron decodes in the language its own audio
  LID chose, so all of its votes count.
"""

from __future__ import annotations

import time
from collections.abc import Collection
from dataclasses import dataclass, field
from typing import Literal

from apps.runtime.services.language_switch.lid.indiclid import TextEvidence

TARGET_LANGUAGES = ("kn", "hi", "mr", "ta", "te")
# Languages whose script identifies them within the five targets.
_SCRIPT_TO_LANGUAGE = {"Knda": "kn", "Taml": "ta", "Telu": "te"}
_SCRIPT_FORCED_LANGUAGES = frozenset(_SCRIPT_TO_LANGUAGE.values())
_LANGUAGE_TO_SCRIPT = {
    "kn": "Knda",
    "ta": "Taml",
    "te": "Telu",
    "hi": "Deva",
    "mr": "Deva",
}
_DEVANAGARI_LANGUAGES = ("hi", "mr")

Source = Literal["main", "nemotron"]


@dataclass(frozen=True)
class JudgeDecision:
    """Selected language with the evidence behind it."""

    outcome: Literal["switch", "stay"]
    language: str  # new language on switch, the active one on stay
    reason: str
    scores: dict[str, float]  # combined weighted evidence per candidate
    evidence: dict[str, TextEvidence | None] = field(default_factory=dict)
    text: str = ""  # transcript the LLM should see for this turn
    text_source: Source = "main"
    previous_language: str = ""  # language being left (set on a switch)


def normalise_language(language: str) -> str:
    """``"Hi-IN"`` -> ``"hi"``: the key form used for language-indexed settings."""
    return (language or "").strip().lower().split("-")[0]


_normalise = normalise_language


class LanguageJudge:
    """Owns the active language and cooldown; ``decide`` is otherwise pure."""

    def __init__(
        self,
        *,
        allowed_languages: Collection[str],
        active_language: str,
        min_score: float = 0.8,
        margin: float = 0.3,
        cooldown_sec: float = 3.0,
        min_words: int = 3,
    ) -> None:
        allowed = {_normalise(lang) for lang in allowed_languages}
        self._candidates = frozenset(allowed & set(TARGET_LANGUAGES))
        self._active = _normalise(active_language)
        self._min_score = min_score
        self._margin = margin
        self._cooldown_sec = cooldown_sec
        self._min_words = min_words
        self._last_switch_at = 0.0

    @property
    def active_language(self) -> str:
        return self._active

    def usable(self, text: str) -> str:
        """``text`` if it is long enough to judge, else ``""``."""
        text = (text or "").strip()
        return text if len(text.split()) >= self._min_words else ""

    def decide(
        self,
        main: TextEvidence | None,
        nemotron: TextEvidence | None,
        *,
        now: float | None = None,
    ) -> JudgeDecision:
        evidence: dict[str, TextEvidence | None] = {"main": main, "nemotron": nemotron}
        scores = self._combine(main, nemotron)

        def stay(reason: str) -> JudgeDecision:
            return JudgeDecision(
                "stay",
                self._active,
                reason,
                scores,
                evidence,
                text=main.text if main else "",
                text_source="main",
            )

        if main is None and nemotron is None:
            return stay("no_text")
        rivals = {
            lang: score
            for lang, score in scores.items()
            if lang != self._active and score > 0
        }
        if not rivals:
            return stay("no_evidence")
        best, best_score = max(rivals.items(), key=lambda item: item[1])
        if best_score < self._min_score:
            return stay("weak_evidence")
        if best_score - scores.get(self._active, 0.0) < self._margin:
            return stay("conflict")
        mono = time.monotonic() if now is None else now
        if self._last_switch_at and mono - self._last_switch_at < self._cooldown_sec:
            return stay("cooldown")

        previous = self._active
        self._active = best
        self._last_switch_at = mono
        source = self._pick_source(best, main, nemotron)
        chosen = main if source == "main" else nemotron
        return JudgeDecision(
            "switch",
            best,
            "switch",
            scores,
            evidence,
            text=chosen.text if chosen else "",
            text_source=source,
            previous_language=previous,
        )

    def _combine(
        self, main: TextEvidence | None, nemotron: TextEvidence | None
    ) -> dict[str, float]:
        scores = dict.fromkeys(sorted(self._candidates), 0.0)
        for source, item in (("main", main), ("nemotron", nemotron)):
            for lang, score in self._votes(item).items():
                if lang not in scores:
                    continue
                if source == "main" and lang in _SCRIPT_FORCED_LANGUAGES:
                    continue  # script forced by the active language
                scores[lang] += score
        return scores

    @staticmethod
    def _votes(item: TextEvidence | None) -> dict[str, float]:
        if item is None:
            return {}
        if item.script in _SCRIPT_TO_LANGUAGE:
            lang = _SCRIPT_TO_LANGUAGE[item.script]
            return {lang: item.scores.get(lang, 0.0)}
        if item.script == "Deva":
            return {lang: item.scores.get(lang, 0.0) for lang in _DEVANAGARI_LANGUAGES}
        return {}

    @staticmethod
    def _pick_source(
        language: str, main: TextEvidence | None, nemotron: TextEvidence | None
    ) -> Source:
        """Transcript whose script matches ``language``; Nemotron's by default."""
        script = _LANGUAGE_TO_SCRIPT[language]
        matching = [
            (source, item)
            for source, item in (("nemotron", nemotron), ("main", main))
            if item is not None and item.script == script
        ]
        if not matching:
            return "nemotron" if nemotron is not None else "main"
        # max() keeps the first of equals, so Nemotron wins ties.
        return max(matching, key=lambda pair: pair[1].scores.get(language, 0.0))[0]
