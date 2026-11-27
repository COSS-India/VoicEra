"""Call recording policy and muting of PII in the stored recording.

Two settings, read on every call:

- ``CALL_RECORDING_ENABLED`` (default ``true``): ``false`` turns call recording
  off. No system recording is made and no carrier recording is started or stored.
- ``PII_REDACTION_ENABLED`` (see ``redaction``): when ``true``, every caller
  utterance and every agent sentence that had something redacted in the
  transcript is replaced with a quiet tone in the stored recording, and carrier
  recordings are not started or stored, because their timing cannot be matched
  to the call reliably and the carrier keeps its own copy.

The tone is the same whatever was removed, like ``[REDACTED_TEXT]`` in text.

Muting follows the text redaction, so it is as good as the transcript: whatever
the speech recognition misheard or the text redaction does not detect (names,
addresses) is not muted either. Speech engines give no word timings, so the unit
is a whole caller utterance or a whole agent sentence, not single words.
"""

from __future__ import annotations

import math
import os
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from apps.runtime.services.privacy import redaction

TONE_HZ = 1000
TONE_LEVEL = 0.06  # about -24 dBFS: clearly a marker, never loud
_FADE_SECS = 0.01

# Seconds of extra audio muted around each part, to cover timing jitter.
USER_PAD_BEFORE = 0.5  # speech starts a little before the turn is detected
USER_PAD_AFTER = 0.3
AGENT_PAD = 0.2


def _falsy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"0", "false", "no", "off"}


def recording_enabled() -> bool:
    """``CALL_RECORDING_ENABLED``; on unless set to false."""
    return not _falsy(os.getenv("CALL_RECORDING_ENABLED"))


def provider_recording_allowed() -> bool:
    """Whether a carrier (provider) recording may be started and stored."""
    return recording_enabled() and not redaction.is_enabled()


# --------------------------------------------------------------------------- #
# Timings
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class TurnTiming:
    """One transcript turn, with when it happened and what was redacted in it."""

    role: str  # "user" or "assistant"
    start: float | None  # epoch seconds; None if the turn's timestamp is unusable
    end: float  # epoch seconds
    content: str
    spans: tuple[tuple[int, int], ...] = field(default_factory=tuple)

    @property
    def has_pii(self) -> bool:
        return bool(self.spans)


@dataclass(frozen=True)
class AgentSegment:
    """A stretch of agent audio, in seconds from the start of the recording."""

    start: float
    end: float
    text: str | None  # the sentence spoken; None if it was cut off


def parse_timestamp(value: str | None) -> float | None:
    """Epoch seconds from Pipecat's ISO 8601 turn timestamp."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).timestamp()  # 3.11+ accepts "Z"
    except ValueError:
        return None


def timings_for_turns(
    turns: Sequence[tuple[str, str | None, float, str]],
    redacted: Sequence[tuple[str, list[tuple[int, int]]]],
) -> list[TurnTiming]:
    """Build ``TurnTiming`` from ``(role, iso_start, epoch_end, content)`` and redaction.

    Caller utterances also count as containing PII when four or more digits are
    read out in them, even if the transcript kept them: the whole utterance is
    muted anyway, so leaning toward muting costs little.
    """
    timings = []
    for (role, iso_start, end, content), (_, spans) in zip(turns, redacted):
        all_spans = list(spans)
        if role == "user" and content:
            all_spans += redaction.find_spans(content, redaction.enabled_entities(), mode="live")
        timings.append(
            TurnTiming(role, parse_timestamp(iso_start), end, content, tuple(sorted(set(all_spans))))
        )
    return timings


# --------------------------------------------------------------------------- #
# Planning what to mute
# --------------------------------------------------------------------------- #


def _overlaps(start: int, end: int, spans: Iterable[tuple[int, int]]) -> bool:
    return any(start < span_end and span_start < end for span_start, span_end in spans)


def _user_windows(turns: Sequence[TurnTiming], started_at: float) -> list[tuple[float, float]]:
    windows = []
    previous_end: float | None = None
    for turn in turns:
        if turn.role != "user":
            continue
        if turn.has_pii:
            # Without a usable start time, mute back to the previous caller turn.
            start = turn.start if turn.start is not None else (previous_end or started_at)
            windows.append((start - started_at - USER_PAD_BEFORE, turn.end - started_at + USER_PAD_AFTER))
        previous_end = turn.end
    return windows


def _agent_turn_at(turns: Sequence[TurnTiming], moment: float) -> TurnTiming | None:
    """The assistant turn whose time range (with some slack) contains ``moment``."""
    for turn in turns:
        if turn.role != "assistant":
            continue
        start = (turn.start if turn.start is not None else turn.end) - 2.0
        if start <= moment <= turn.end + 2.0:
            return turn
    return None


def _agent_windows(
    turns: Sequence[TurnTiming], segments: Sequence[AgentSegment], started_at: float
) -> list[tuple[float, float]]:
    """Mute each agent sentence that overlaps something redacted in its turn.

    Sentences are matched to the assistant turns' text in order (an assistant
    turn's text is the sentences it spoke). A sentence that cannot be matched,
    or a cut-off stretch with no text, is muted if its turn had anything
    redacted, or if the sentence on its own contains PII.
    """
    assistant = [turn for turn in turns if turn.role == "assistant"]
    windows = []
    turn_index, cursor = 0, 0
    for segment in segments:
        mute = False
        located = False
        text = (segment.text or "").strip()
        if text:
            for index in range(turn_index, len(assistant)):
                position = assistant[index].content.find(text, cursor if index == turn_index else 0)
                if position >= 0:
                    turn_index, cursor = index, position + len(text)
                    mute = _overlaps(position, cursor, assistant[index].spans)
                    located = True
                    break
        if not located:
            turn = _agent_turn_at(turns, started_at + (segment.start + segment.end) / 2)
            mute = bool(turn and turn.has_pii) or bool(
                text and redaction.find_spans(text, redaction.enabled_entities())
            )
        if mute:
            windows.append((segment.start - AGENT_PAD, segment.end + AGENT_PAD))
    return windows


def plan_mutes(
    turns: Sequence[TurnTiming], segments: Sequence[AgentSegment], started_at: float
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """``(caller_windows, agent_windows)`` in seconds from the start of the recording."""
    return _user_windows(turns, started_at), _agent_windows(turns, segments, started_at)


# --------------------------------------------------------------------------- #
# Audio
# --------------------------------------------------------------------------- #


def _merge(windows: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    merged: list[tuple[float, float]] = []
    for start, end in sorted((max(0.0, s), e) for s, e in windows if e > 0):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def tone(samples: int, sample_rate: int) -> np.ndarray:
    """A quiet sine tone with short fades, as 16-bit samples."""
    t = np.arange(samples) / sample_rate
    wave = np.sin(2 * math.pi * TONE_HZ * t) * TONE_LEVEL
    fade = min(samples // 2, int(sample_rate * _FADE_SECS))
    if fade:
        ramp = np.linspace(0.0, 1.0, fade)
        wave[:fade] *= ramp
        wave[-fade:] *= ramp[::-1]
    return (wave * 32767).astype("<i2")


def mute(track: bytes, sample_rate: int, windows: Iterable[tuple[float, float]]) -> bytes:
    """Replace each window (seconds) of a 16-bit mono track with the tone."""
    samples = np.frombuffer(track, dtype="<i2").copy()
    for start, end in _merge(windows):
        first = int(start * sample_rate)
        last = min(len(samples), math.ceil(end * sample_rate))
        if first < last:
            samples[first:last] = tone(last - first, sample_rate)
    return samples.tobytes()
