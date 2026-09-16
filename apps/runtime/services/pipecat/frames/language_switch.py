"""Custom Pipecat frame requesting a mid-call language switch."""

from __future__ import annotations

from dataclasses import dataclass

from pipecat.frames.frames import ControlFrame, UninterruptibleFrame


@dataclass
class LanguageSwitchFrame(ControlFrame, UninterruptibleFrame):
    """Request to switch the active conversation language.

    Provider-agnostic: carries only the target language id. STT/TTS/LLM
    configuration is resolved by ``LanguageSwitchProcessor`` from
    ``language_models``.

    Parameters:
        language: Canonical language id such as ``hi``, ``kn``, ``ml``, ``en``.
    """

    language: str
