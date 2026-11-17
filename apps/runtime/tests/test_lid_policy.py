"""Unit tests for LidPolicy switch/stay gates."""

from __future__ import annotations

import unittest

from apps.runtime.services.language_switch.lid.policy import LidPolicy
from apps.runtime.services.language_switch.lid.types import LidResult


def _result(code: str, confidence: float = 0.9) -> LidResult:
    return LidResult(language_code=code, confidence=confidence, duration_sec=2.0)


class TestLidPolicy(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = LidPolicy(
            allowed_languages=frozenset({"hi", "mr", "ta"}),
            min_confidence=0.7,
            min_audio_sec=1.8,
            cooldown_sec=3.0,
            active_language="hi",
        )

    def test_switch_when_confident_supported_and_different(self) -> None:
        decision = self.policy.decide(_result("mr"), buffered_audio_sec=2.0, now=100.0)
        self.assertEqual(decision.outcome, "switch")
        self.assertEqual(decision.language, "mr")
        self.assertEqual(decision.reason, "lid_switch")

    def test_stay_on_short_audio(self) -> None:
        decision = self.policy.decide(_result("mr"), buffered_audio_sec=1.0, now=100.0)
        self.assertEqual(decision.outcome, "stay")
        self.assertEqual(decision.reason, "short_audio")

    def test_stay_on_low_confidence(self) -> None:
        decision = self.policy.decide(
            _result("mr", confidence=0.4),
            buffered_audio_sec=2.0,
            now=100.0,
        )
        self.assertEqual(decision.outcome, "stay")
        self.assertEqual(decision.reason, "low_confidence")

    def test_stay_when_already_active(self) -> None:
        decision = self.policy.decide(_result("hi"), buffered_audio_sec=2.0, now=100.0)
        self.assertEqual(decision.outcome, "stay")
        self.assertEqual(decision.reason, "already_active")

    def test_stay_when_not_in_agent_allowlist(self) -> None:
        decision = self.policy.decide(_result("bn"), buffered_audio_sec=2.0, now=100.0)
        self.assertEqual(decision.outcome, "stay")
        self.assertEqual(decision.reason, "unsupported_language")

    def test_stay_when_not_in_probe(self) -> None:
        decision = self.policy.decide(_result("en"), buffered_audio_sec=2.0, now=100.0)
        self.assertEqual(decision.outcome, "stay")
        self.assertEqual(decision.reason, "not_in_probe")

    def test_stay_during_cooldown(self) -> None:
        self.policy.note_switch("mr", at=100.0)
        decision = self.policy.decide(_result("ta"), buffered_audio_sec=2.0, now=101.0)
        self.assertEqual(decision.outcome, "stay")
        self.assertEqual(decision.reason, "cooldown")

    def test_switch_after_cooldown(self) -> None:
        self.policy.note_switch("mr", at=100.0)
        decision = self.policy.decide(_result("ta"), buffered_audio_sec=2.0, now=104.0)
        self.assertEqual(decision.outcome, "switch")
        self.assertEqual(decision.language, "ta")

    def test_missing_language_stays(self) -> None:
        decision = self.policy.decide(
            LidResult(language_code="", confidence=0.9),
            buffered_audio_sec=2.0,
            now=100.0,
        )
        self.assertEqual(decision.outcome, "stay")
        self.assertEqual(decision.reason, "missing_language")


if __name__ == "__main__":
    unittest.main()
