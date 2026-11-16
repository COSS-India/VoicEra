"""Hold playback strategies: TTS text vs pre-recorded PCM audio."""

from __future__ import annotations

from typing import Any, Protocol

from loguru import logger
from pipecat.frames.frames import OutputAudioRawFrame, TTSSpeakFrame

from apps.runtime.services.pipecat.hold.clips import (
    AudioHoldClip,
    HoldClip,
    TextHoldClip,
)

# ~20 ms of 16-bit mono PCM per chunk.
_CHUNK_MS = 20


class HoldPlayer(Protocol):
    async def play(self, clip: HoldClip) -> None: ...


class TextHoldPlayer:
    """Speak a hold phrase through the TTS service."""

    def __init__(self, tts: Any) -> None:
        self._tts = tts

    async def play(self, clip: HoldClip) -> None:
        if not isinstance(clip, TextHoldClip):
            logger.warning("TextHoldPlayer received non-text clip; skipping")
            return
        await self._tts.queue_frame(
            TTSSpeakFrame(clip.text, append_to_context=False),
        )


class AudioHoldPlayer:
    """Queue preloaded PCM as OutputAudioRawFrame chunks through TTS."""

    def __init__(self, tts: Any) -> None:
        self._tts = tts

    async def play(self, clip: HoldClip) -> None:
        if not isinstance(clip, AudioHoldClip):
            logger.warning("AudioHoldPlayer received non-audio clip; skipping")
            return
        pcm = clip.pcm or b""
        sample_rate = int(clip.sample_rate or 0)
        if not pcm or sample_rate <= 0:
            logger.warning(
                "Audio hold clip {} has no prepared PCM; skipping",
                clip.clip_id,
            )
            return

        bytes_per_chunk = max(sample_rate * 2 * _CHUNK_MS // 1000, 2)
        # Keep even byte length for 16-bit samples.
        if bytes_per_chunk % 2:
            bytes_per_chunk += 1

        for offset in range(0, len(pcm), bytes_per_chunk):
            chunk = pcm[offset : offset + bytes_per_chunk]
            if len(chunk) < 2:
                break
            if len(chunk) % 2:
                chunk = chunk[:-1]
            await self._tts.queue_frame(
                OutputAudioRawFrame(
                    audio=chunk,
                    sample_rate=sample_rate,
                    num_channels=1,
                )
            )


def player_for_mode(mode: str, tts: Any) -> HoldPlayer:
    if mode == "audio":
        return AudioHoldPlayer(tts)
    return TextHoldPlayer(tts)
