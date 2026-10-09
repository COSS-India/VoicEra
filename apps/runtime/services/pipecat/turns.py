"""User turn stop strategy that releases transcript-started turns without delay."""

from __future__ import annotations

from pipecat.frames.frames import TranscriptionFrame
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy


class FinalizedTranscriptUserTurnStopStrategy(TurnAnalyzerUserTurnStopStrategy):
    """Release the user turn as soon as a finalized transcript arrives in fallback mode.

    With ``MinWordsUserTurnStartStrategy`` the user turn starts on a transcript,
    which usually lands after ``VADUserStoppedSpeakingFrame``. Starting the turn
    resets this strategy and drops the VAD stop it already saw, so the same
    transcript is handled in pipecat's no-VAD-stop fallback. That fallback arms
    a ``ttfs_p99_latency - stop_secs`` timer (1.0 - 0.4 = 0.6s by default) and
    ignores ``finalized``, idling every turn before the LLM is called.

    A finalized transcript means the STT has nothing more to send, so release
    the turn immediately instead of waiting out that timer. Non-finalized
    transcripts keep pipecat's fallback timer.
    """

    async def _handle_transcription(self, frame: TranscriptionFrame):
        await super()._handle_transcription(frame)
        in_fallback = not self._vad_user_speaking and not self._vad_stopped
        if frame.finalized and in_fallback:
            await self._maybe_trigger_user_turn_stopped()
