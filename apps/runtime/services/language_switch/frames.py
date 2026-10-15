"""Control frames for mid-call language switching."""

from __future__ import annotations

from dataclasses import dataclass

from pipecat.frames.frames import ControlFrame


@dataclass
class LanguageSwitchFrame(ControlFrame):
    """Request a switch to another configured agent language."""

    language: str
