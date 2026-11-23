"""Accumulate user-speech PCM for one utterance and export WAV / snapshots."""

from __future__ import annotations

import audioop
import io
import wave

TARGET_SAMPLE_RATE = 16_000


class SpeechBuffer:
    """Collect int16 mono PCM while the caller is speaking."""

    def __init__(self, sample_rate: int) -> None:
        if sample_rate <= 0:
            raise ValueError(f"sample_rate must be positive, got {sample_rate}")
        self._sample_rate = int(sample_rate)
        self._chunks: list[bytes] = []
        self._bytes = 0

    def reset(self) -> None:
        self._chunks.clear()
        self._bytes = 0

    def append(self, pcm: bytes) -> None:
        if not pcm:
            return
        self._chunks.append(pcm)
        self._bytes += len(pcm)

    def trim_to_max_duration(self, max_sec: float) -> None:
        """Drop oldest PCM so the buffer is at most ``max_sec`` long."""
        if max_sec <= 0 or self._bytes <= 0:
            return
        max_bytes = int(max_sec * 2.0 * self._sample_rate)
        max_bytes -= max_bytes % 2
        if max_bytes <= 0 or self._bytes <= max_bytes:
            return
        drop = self._bytes - max_bytes
        while drop > 0 and self._chunks:
            head = self._chunks[0]
            if len(head) <= drop:
                self._chunks.pop(0)
                self._bytes -= len(head)
                drop -= len(head)
            else:
                cut = drop - (drop % 2)
                if cut <= 0:
                    break
                self._chunks[0] = head[cut:]
                self._bytes -= cut
                drop -= cut

    def keep_last(self, max_sec: float) -> None:
        """Alias for ``trim_to_max_duration`` — retain only a trailing pre-roll."""
        self.trim_to_max_duration(max_sec)

    @property
    def sample_rate(self) -> int:
        return self._sample_rate

    @property
    def byte_length(self) -> int:
        return self._bytes

    @property
    def duration_sec(self) -> float:
        if self._sample_rate <= 0 or self._bytes <= 0:
            return 0.0
        return self._bytes / (2.0 * self._sample_rate)

    def pcm_snapshot(self) -> bytes | None:
        """Return concatenated PCM without draining the buffer."""
        if self._bytes <= 0:
            return None
        return b"".join(self._chunks)

    def wav_16k_from_pcm(self, pcm: bytes) -> bytes:
        """Encode ``pcm`` (this buffer's sample rate) as 16 kHz mono WAV."""
        if self._sample_rate != TARGET_SAMPLE_RATE:
            pcm, _ = audioop.ratecv(pcm, 2, 1, self._sample_rate, TARGET_SAMPLE_RATE, None)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(TARGET_SAMPLE_RATE)
            wf.writeframes(pcm)
        return buf.getvalue()

    def take_wav_16k(self) -> bytes | None:
        """Drain the buffer and return a 16 kHz mono WAV, or None if empty."""
        pcm = self.pcm_snapshot()
        self.reset()
        if not pcm:
            return None
        return self.wav_16k_from_pcm(pcm)
