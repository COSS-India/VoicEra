"""Control frames for mid-call language switching."""

from __future__ import annotations

from dataclasses import dataclass

from pipecat.frames.frames import ControlFrame


@dataclass
class LanguageSwitchFrame(ControlFrame):
    """Request a switch to another configured agent language."""

    language: str


@dataclass
class NemotronTranscriptFrame(ControlFrame):
    """Nemotron ASR transcript of the utterance that just ended.

    Emitted exactly once per utterance; ``text`` is empty when Nemotron was
    skipped, failed, or was superseded by new speech.
    """

    text: str = ""
