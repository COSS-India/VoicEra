"""Portuguese Whisper STT for Pipecat.

model-server's ``stt/pt-whisper`` speaks the same ``/v1/asr/ws`` protocol as
``indic-nemotron`` -- ready on connect, PCM16 in, partials out, ``flush_eos``
on the pipeline's VAD stop -- so the client is the Nemotron one, with one
difference.

Whisper hallucinates. Fed a breath, line noise or the tail of an utterance it
will happily return a word ("Tinha", "Obrigado"), and Nemotron never did. An
interim transcript is what Pipecat's turn-start strategy listens to, so one
such word arriving while the LLM is answering is read as the caller starting
to speak -- and the answer is cancelled before it is spoken. That is exactly
what the first nees-demo call did.

So partials are only passed on while the pipeline's own Silero VAD says the
caller is speaking. Anything the server sends outside that window is noise by
definition: the turn has either not started or has already been committed
with ``flush_eos``. Finals are untouched.
"""

from __future__ import annotations

from pipecat.frames.frames import (
    Frame,
    InterimTranscriptionFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.processors.frame_processor import FrameDirection

from ..indic_nemotron.stt import IndicNemotronSTTService


class PtWhisperSTTService(IndicNemotronSTTService):
    """Stream PCM to model-server ``/v1/asr/ws`` (pt-whisper)."""

    def __init__(self, *, ws_url: str, language: str = "pt", **kwargs):
        super().__init__(ws_url=ws_url, language=language, **kwargs)
        self._vad_speaking = False

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        # Flip the gate BEFORE the parent handles the frame: on a stop it sends
        # flush_eos, and any partial racing back after that must be dropped.
        if isinstance(frame, VADUserStartedSpeakingFrame):
            self._vad_speaking = True
        elif isinstance(frame, VADUserStoppedSpeakingFrame):
            self._vad_speaking = False
        await super().process_frame(frame, direction)

    async def push_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        if isinstance(frame, InterimTranscriptionFrame) and not self._vad_speaking:
            return
        await super().push_frame(frame, direction)
