"""Load hold WAV/MP3 clips from MinIO, decode PCM, and resample to pipeline rate."""

from __future__ import annotations

import array
import asyncio
import io
import wave
from pathlib import Path
from typing import Any

from loguru import logger
from pipecat.audio.utils import create_file_resampler

from apps.runtime.services.pipecat.hold.clips import (
    AudioHoldClip,
    assert_org_owned_key,
)
from apps.runtime.services.storage import object_storage


def _mix_stereo_to_mono(pcm: bytes) -> bytes:
    """Average interleaved 16-bit stereo PCM into mono."""
    samples = array.array("h")
    samples.frombytes(pcm)
    if len(samples) % 2:
        samples = samples[:-1]
    mono = array.array("h")
    for i in range(0, len(samples), 2):
        mono.append((samples[i] + samples[i + 1]) // 2)
    return mono.tobytes()


def _looks_like_wav(data: bytes) -> bool:
    return len(data) >= 12 and data[0:4] == b"RIFF" and data[8:12] == b"WAVE"


def _looks_like_mp3(data: bytes) -> bool:
    if len(data) < 3:
        return False
    if data.startswith(b"ID3"):
        return True
    # MPEG audio frame sync.
    return data[0] == 0xFF and (data[1] & 0xE0) == 0xE0


def decode_wav_pcm(data: bytes) -> tuple[bytes, int]:
    """Decode 16-bit PCM WAV to mono PCM bytes and source sample rate."""
    with wave.open(io.BytesIO(data), "rb") as wf:
        channels = wf.getnchannels()
        sample_width = wf.getsampwidth()
        sample_rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    if sample_width != 2:
        raise ValueError("hold audio must be 16-bit PCM WAV")
    if channels == 2:
        frames = _mix_stereo_to_mono(frames)
    elif channels != 1:
        raise ValueError("hold audio must be mono or stereo WAV")
    if sample_rate <= 0 or not frames:
        raise ValueError("hold audio WAV has no audio frames")
    return frames, int(sample_rate)


def decode_mp3_pcm(data: bytes, *, target_rate: int | None = None) -> tuple[bytes, int]:
    """Decode MP3 to mono 16-bit PCM via miniaudio."""
    import miniaudio

    sample_rate = int(target_rate) if target_rate and target_rate > 0 else 0
    # sample_rate=0 keeps the source rate when supported; fall back to decode defaults.
    kwargs: dict[str, Any] = {
        "output_format": miniaudio.SampleFormat.SIGNED16,
        "nchannels": 1,
    }
    if sample_rate > 0:
        kwargs["sample_rate"] = sample_rate
    else:
        # Keep a stable default; caller may resample afterward.
        kwargs["sample_rate"] = 16000

    try:
        if sample_rate <= 0:
            info = miniaudio.mp3_get_info(data)
            source_rate = int(getattr(info, "sample_rate", 0) or 0)
            if source_rate > 0:
                kwargs["sample_rate"] = source_rate
        decoded = miniaudio.decode(data, **kwargs)
    except Exception as exc:
        raise ValueError(f"invalid hold audio MP3: {exc}") from exc

    pcm = decoded.samples.tobytes()
    rate = int(decoded.sample_rate)
    if rate <= 0 or not pcm:
        raise ValueError("hold audio MP3 has no audio frames")
    return pcm, rate


def detect_format(data: bytes, filename: str | None = None) -> str:
    """Return ``wav`` or ``mp3`` from magic bytes, falling back to filename."""
    if _looks_like_wav(data):
        return "wav"
    if _looks_like_mp3(data):
        return "mp3"
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".wav":
        return "wav"
    if suffix == ".mp3":
        return "mp3"
    raise ValueError("unsupported hold audio format (expected WAV or MP3)")


def decode_hold_pcm(
    data: bytes,
    *,
    filename: str | None = None,
    target_rate: int | None = None,
) -> tuple[bytes, int]:
    """Decode a hold clip to mono PCM and its sample rate."""
    fmt = detect_format(data, filename)
    if fmt == "wav":
        return decode_wav_pcm(data)
    return decode_mp3_pcm(data, target_rate=target_rate)


async def _resample_pcm(
    pcm: bytes,
    *,
    source_rate: int,
    target_rate: int,
) -> bytes:
    if source_rate == target_rate:
        return pcm
    resampler = create_file_resampler()
    return await resampler.resample(pcm, source_rate, target_rate)


async def load_audio_clip(
    clip: AudioHoldClip,
    *,
    org_id: str,
    sample_rate: int,
    fetch_bytes: Any | None = None,
) -> AudioHoldClip | None:
    """Fetch, decode, and resample one clip. Returns ``None`` on failure."""
    if not assert_org_owned_key(org_id, clip.storage_key):
        logger.warning(
            "Skipping hold clip {}: storage_key not owned by org {}",
            clip.clip_id,
            org_id,
        )
        return None

    fetcher = fetch_bytes or object_storage.get_object_bytes
    raw = await fetcher(clip.storage_key)
    if not raw:
        logger.warning(
            "Skipping hold clip {}: failed to download {}",
            clip.clip_id,
            clip.storage_key,
        )
        return None

    try:
        # Let miniaudio resample MP3 directly to pipeline rate when possible.
        pcm, source_rate = await asyncio.to_thread(
            decode_hold_pcm,
            raw,
            filename=clip.filename,
            target_rate=sample_rate,
        )
        pcm = await _resample_pcm(
            pcm, source_rate=source_rate, target_rate=sample_rate
        )
    except Exception:
        logger.warning(
            "Skipping hold clip {}: decode/resample failed",
            clip.clip_id,
            exc_info=True,
        )
        return None

    if not pcm:
        logger.warning("Skipping hold clip {}: empty PCM after decode", clip.clip_id)
        return None

    return AudioHoldClip(
        clip_id=clip.clip_id,
        storage_key=clip.storage_key,
        filename=clip.filename,
        pcm=pcm,
        sample_rate=sample_rate,
    )


async def preload_audio_clips(
    clips: tuple[AudioHoldClip, ...],
    *,
    org_id: str,
    sample_rate: int,
    fetch_bytes: Any | None = None,
) -> tuple[AudioHoldClip, ...]:
    """Load all clips; drop failures. May return an empty tuple."""
    loaded: list[AudioHoldClip] = []
    for clip in clips:
        ready = await load_audio_clip(
            clip,
            org_id=org_id,
            sample_rate=sample_rate,
            fetch_bytes=fetch_bytes,
        )
        if ready is not None:
            loaded.append(ready)
    return tuple(loaded)
