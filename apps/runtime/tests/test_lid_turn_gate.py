"""LidTurnGate: hold, judge, switch/release behaviour."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock

from pipecat.frames.frames import (
    EndFrame,
    TextFrame,
    TranscriptionFrame,
    TTSSpeakFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from apps.runtime.services.language_switch.frames import (
    LanguageSwitchFrame,
    NemotronTranscriptFrame,
)
from apps.runtime.services.language_switch.lid.indiclid import TextEvidence, script_of
from apps.runtime.services.language_switch.lid.judge import LanguageJudge
from apps.runtime.services.language_switch.turn_gate import LidTurnGate

DOWN, UP = FrameDirection.DOWNSTREAM, FrameDirection.UPSTREAM

KN = "ನಮಸ್ಕಾರ ನೀವು ಹೇಗಿದ್ದೀರಿ"
KN_DEVA = "नमस्कार निवु हेगिद्दीरी"
HI = "मुझे अपने खाते की जानकारी चाहिए"
MR = "मला माझ्या खात्याची माहिती हवी आहे"
SHORT = "हाँ"


def ev(text: str, **scores: float) -> TextEvidence:
    full = {lang: scores.get(lang, 0.0) for lang in ("kn", "hi", "mr", "ta", "te")}
    return TextEvidence(text=text, script=script_of(text), scores=full)


class _FakeIndicLid:
    """Returns the evidence registered for each text; None for unknown/empty."""

    def __init__(self, table: dict[str, TextEvidence], *, delay: float = 0.0, fail=False):
        self.table, self.delay, self.fail = table, delay, fail
        self.calls: list[list[str]] = []
        self.closed = False

    async def score(self, texts):
        self.calls.append(list(texts))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            return [None] * len(texts)
        return [self.table.get(t) if t else None for t in texts]

    async def aclose(self):
        self.closed = True


def _final(text: str) -> TranscriptionFrame:
    return TranscriptionFrame(text=text, user_id="u", timestamp="t", finalized=True)


def _make(table=None, *, active="hi", deadline=0.15, handoff_messages=None, **client_kw):
    client = _FakeIndicLid(table or {}, **client_kw)
    gate = LidTurnGate(
        judge=LanguageJudge(
            allowed_languages=("kn", "hi", "mr", "ta", "te"),
            active_language=active,
            cooldown_sec=0.0,
        ),
        client=client,
        hold_deadline_s=deadline,
        handoff_messages=handoff_messages,
    )
    pushed: list = []

    async def _capture(frame, direction=DOWN):  # noqa: ANN001
        pushed.append((frame, direction))

    gate.push_frame = AsyncMock(side_effect=_capture)  # type: ignore[method-assign]
    return gate, client, pushed


def _texts(pushed) -> list[str]:
    return [f.text for f, _ in pushed if isinstance(f, TranscriptionFrame)]


def _spoken(pushed) -> list[TTSSpeakFrame]:
    return [f for f, _ in pushed if isinstance(f, TTSSpeakFrame)]


def _switches(pushed) -> list[tuple[str, FrameDirection]]:
    return [(f.language, d) for f, d in pushed if isinstance(f, LanguageSwitchFrame)]


async def _settle(gate: LidTurnGate) -> None:
    for _ in range(100):
        await asyncio.sleep(0.01)
        if not gate._awaiting and gate._resolve_task is None:  # noqa: SLF001
            return
    raise AssertionError("gate never resolved")


async def _utterance(gate, main: list[str], nemotron: str | None, *, stop=True) -> None:
    await gate.process_frame(VADUserStartedSpeakingFrame(), UP)
    for text in main:
        await gate.process_frame(_final(text), DOWN)
    if stop:
        await gate.process_frame(VADUserStoppedSpeakingFrame(), UP)
    if nemotron is not None:
        await gate.process_frame(NemotronTranscriptFrame(text=nemotron), DOWN)


class TestLidTurnGate(unittest.IsolatedAsyncioTestCase):
    async def test_idle_finals_pass_straight_through(self) -> None:
        gate, client, pushed = _make()
        await gate.process_frame(_final("hello there friend"), DOWN)
        self.assertEqual(_texts(pushed), ["hello there friend"])
        self.assertEqual(client.calls, [])

    async def test_finals_are_held_while_speaking(self) -> None:
        gate, _client, pushed = _make()
        await _utterance(gate, [HI], None, stop=False)
        self.assertEqual(_texts(pushed), [])

    async def test_same_language_releases_main_text(self) -> None:
        gate, client, pushed = _make({HI: ev(HI, hi=1.0)})
        await _utterance(gate, [HI], HI)
        await _settle(gate)

        self.assertEqual(_texts(pushed), [HI])
        self.assertEqual(client.calls, [[HI, HI]])
        self.assertEqual(_switches(pushed), [])

    async def test_kannada_example_stays_kannada(self) -> None:
        gate, _client, pushed = _make({KN: ev(KN, kn=1.0), KN_DEVA: ev(KN_DEVA, mr=0.572)}, active="kn")
        await _utterance(gate, [KN], KN_DEVA)
        await _settle(gate)
        self.assertEqual(_texts(pushed), [KN])
        self.assertEqual(_switches(pushed), [])

    async def test_switch_uses_chosen_transcript_and_broadcasts_language(self) -> None:
        garbled = "आप कैसे हैं नमस्ते"
        gate, _client, pushed = _make({garbled: ev(garbled), KN: ev(KN, kn=1.0)})
        await _utterance(gate, [garbled], KN)
        await _settle(gate)

        self.assertEqual(_texts(pushed), [KN])  # main text dropped
        self.assertEqual(
            sorted(_switches(pushed), key=lambda x: x[1].value),
            sorted([("kn", DOWN), ("kn", UP)], key=lambda x: x[1].value),
        )
        order = [type(f).__name__ for f, d in pushed if d == DOWN]
        self.assertLess(order.index("LanguageSwitchFrame"), order.index("TranscriptionFrame"))
        final = next(f for f, _ in pushed if isinstance(f, TranscriptionFrame))
        self.assertTrue(final.finalized)

    async def test_handoff_message_is_the_one_for_the_language_being_left(self) -> None:
        gate, _client, pushed = _make(
            {KN: ev(KN, kn=1.0), HI: ev(HI)},
            handoff_messages={"hi": "  ek minute  ", "kn": "ಒಂದು ನಿಮಿಷ"},
        )
        await _utterance(gate, [HI], KN)  # hi -> kn
        await _settle(gate)

        spoken = _spoken(pushed)
        self.assertEqual([f.text for f in spoken], ["ek minute"])  # hi's, not kn's
        # Filler, not something the agent "said": keep it out of the LLM context.
        self.assertFalse(spoken[0].append_to_context)

    async def test_handoff_message_reaches_the_old_tts_before_the_switch(self) -> None:
        gate, _client, pushed = _make(
            {KN: ev(KN, kn=1.0), HI: ev(HI)}, handoff_messages={"hi": "ek minute"}
        )
        await _utterance(gate, [HI], KN)
        await _settle(gate)

        order = [type(f).__name__ for f, d in pushed if d == DOWN]
        self.assertEqual(
            order, ["TTSSpeakFrame", "LanguageSwitchFrame", "TranscriptionFrame"]
        )

    async def test_each_switch_uses_the_language_it_leaves(self) -> None:
        garbled = "आप कैसे हैं नमस्ते"  # main ASR forced into Devanagari: no real evidence
        gate, _client, pushed = _make(
            {garbled: ev(garbled), KN: ev(KN, kn=1.0), MR: ev(MR, mr=2.0)},
            handoff_messages={"hi": "hindi message", "kn": "kannada message", "mr": "marathi message"},
        )
        await _utterance(gate, [garbled], KN)  # hi -> kn
        await _settle(gate)
        await _utterance(gate, [KN], MR)  # kn -> mr
        await _settle(gate)
        self.assertEqual(
            [f.text for f in _spoken(pushed)], ["hindi message", "kannada message"]
        )

    async def test_no_message_for_the_language_being_left_means_silence(self) -> None:
        gate, _client, pushed = _make(
            {KN: ev(KN, kn=1.0), HI: ev(HI)}, handoff_messages={"kn": "only for kannada"}
        )
        await _utterance(gate, [HI], KN)
        await _settle(gate)
        self.assertEqual(_spoken(pushed), [])
        self.assertEqual(len(_switches(pushed)), 2)  # the switch itself still happens

    async def test_region_suffixed_keys_and_active_language_match(self) -> None:
        gate, _client, pushed = _make(
            {KN: ev(KN, kn=1.0), HI: ev(HI)}, handoff_messages={"HI-IN": "ek minute"}
        )
        await _utterance(gate, [HI], KN)
        await _settle(gate)
        self.assertEqual([f.text for f in _spoken(pushed)], ["ek minute"])

    async def test_handoff_message_is_not_played_when_language_stays(self) -> None:
        gate, _client, pushed = _make({HI: ev(HI, hi=1.0)}, handoff_messages={"hi": "ek minute"})
        await _utterance(gate, [HI], HI)
        await _settle(gate)
        self.assertEqual(_spoken(pushed), [])
        self.assertEqual(_texts(pushed), [HI])

    async def test_handoff_message_is_not_played_when_judging_fails(self) -> None:
        gate, _client, pushed = _make(handoff_messages={"hi": "ek minute"}, fail=True)
        await _utterance(gate, [HI], KN)
        await _settle(gate)
        self.assertEqual(_spoken(pushed), [])

    async def test_no_handoff_messages_by_default(self) -> None:
        gate, _client, pushed = _make({KN: ev(KN, kn=1.0), HI: ev(HI)})
        await _utterance(gate, [HI], KN)
        await _settle(gate)
        self.assertEqual(len(_switches(pushed)), 2)
        self.assertEqual(_spoken(pushed), [])

    async def test_late_old_stt_finals_dropped_until_next_speech(self) -> None:
        gate, _client, pushed = _make({KN: ev(KN, kn=1.0), HI: ev(HI)})
        await _utterance(gate, [HI], KN)
        await _settle(gate)
        await gate.process_frame(_final("old stt late final"), DOWN)
        self.assertEqual(_texts(pushed), [KN])

        await gate.process_frame(VADUserStartedSpeakingFrame(), UP)
        await gate.process_frame(VADUserStoppedSpeakingFrame(), UP)
        await gate.process_frame(_final("next turn"), DOWN)
        # The new utterance is no longer suppressed: its final is held for judging.
        self.assertEqual([t.text for t in gate._held], ["next turn"])  # noqa: SLF001
        self.assertEqual(_texts(pushed), [KN])

    async def test_deadline_releases_main_when_nemotron_never_arrives(self) -> None:
        gate, client, pushed = _make({HI: ev(HI, hi=1.0)})
        await _utterance(gate, [HI], None)
        await _settle(gate)

        self.assertEqual(_texts(pushed), [HI])
        self.assertEqual(client.calls, [[HI, ""]])

    async def test_nemotron_alone_can_switch_when_main_is_silent(self) -> None:
        gate, _client, pushed = _make({KN: ev(KN, kn=1.0)})
        await _utterance(gate, [], KN)
        await _settle(gate)  # waits for the hold deadline: no main final arrived

        self.assertEqual(_texts(pushed), [KN])
        self.assertEqual(len(_switches(pushed)), 2)

    async def test_indiclid_failure_releases_main(self) -> None:
        gate, _client, pushed = _make(fail=True)
        await _utterance(gate, [HI], KN)
        await _settle(gate)
        self.assertEqual(_texts(pushed), [HI])
        self.assertEqual(_switches(pushed), [])

    async def test_short_transcripts_are_not_scored(self) -> None:
        gate, client, pushed = _make()
        await _utterance(gate, [SHORT], SHORT)
        await _settle(gate)
        self.assertEqual(client.calls, [])
        self.assertEqual(_texts(pushed), [SHORT])

    async def test_empty_nemotron_text_releases_main(self) -> None:
        gate, client, pushed = _make({HI: ev(HI, hi=1.0)})
        await _utterance(gate, [HI], "")
        await _settle(gate)
        self.assertEqual(client.calls, [[HI, ""]])
        self.assertEqual(_texts(pushed), [HI])

    async def test_new_speech_during_judging_keeps_holding(self) -> None:
        gate, _client, pushed = _make({HI: ev(HI, hi=1.0)}, delay=5.0)
        await _utterance(gate, [HI], HI)
        await asyncio.sleep(0.05)
        await gate.process_frame(VADUserStartedSpeakingFrame(), UP)

        self.assertEqual(_texts(pushed), [])  # still held for the new utterance
        self.assertIsNone(gate._resolve_task)  # noqa: SLF001
        await gate.process_frame(VADUserStoppedSpeakingFrame(), UP)

    async def test_stale_nemotron_frame_is_ignored_and_never_forwarded(self) -> None:
        gate, client, pushed = _make()
        frame = NemotronTranscriptFrame(text=KN)
        await gate.process_frame(frame, DOWN)
        self.assertEqual(pushed, [])
        self.assertEqual(client.calls, [])

    async def test_other_frames_and_deterministic_switch_pass_through(self) -> None:
        gate, _client, pushed = _make()
        text = TextFrame(text="hello")
        switch = LanguageSwitchFrame(language="ta")
        await gate.process_frame(text, DOWN)
        await gate.process_frame(switch, DOWN)
        self.assertEqual([f for f, _ in pushed], [text, switch])

    async def test_end_frame_closes_client_and_cancels_tasks(self) -> None:
        gate, client, _pushed = _make(delay=5.0)
        await _utterance(gate, [HI], HI)
        await asyncio.sleep(0.05)
        await gate.process_frame(EndFrame(), DOWN)
        self.assertTrue(client.closed)
        self.assertIsNone(gate._resolve_task)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
