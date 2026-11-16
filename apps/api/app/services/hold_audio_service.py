"""Org-scoped hold-audio WAV/MP3 uploads in MinIO (no Mongo metadata table)."""

from __future__ import annotations

import logging
import uuid
import wave
from io import BytesIO
from pathlib import Path
from typing import Any, Literal

from app.config import settings

logger = logging.getLogger(__name__)

HOLD_AUDIO_PREFIX = "hold-audio"
HoldAudioFormat = Literal["wav", "mp3"]
_ALLOWED_EXTENSIONS = frozenset({".wav", ".mp3"})
_CONTENT_TYPES = {
    "wav": "audio/wav",
    "mp3": "audio/mpeg",
}


class HoldAudioError(ValueError):
    """Invalid hold-audio upload or storage key."""


def org_prefix(org_id: str) -> str:
    return f"{HOLD_AUDIO_PREFIX}/{org_id}/"


def storage_key_for(org_id: str, clip_id: str, filename: str) -> str:
    safe_name = Path(filename).name or "hold.wav"
    return f"{HOLD_AUDIO_PREFIX}/{org_id}/{clip_id}/{safe_name}"


def assert_org_storage_key(org_id: str, storage_key: str) -> None:
    prefix = org_prefix(org_id)
    key = (storage_key or "").strip()
    if not key.startswith(prefix):
        raise HoldAudioError(
            f"hold_audio_clips.storage_key must start with {prefix!r}"
        )
    remainder = key[len(prefix) :]
    if not remainder or ".." in remainder.split("/"):
        raise HoldAudioError("hold_audio_clips.storage_key is invalid")


def _extension_format(filename: str) -> HoldAudioFormat | None:
    suffix = Path(filename).suffix.lower()
    if suffix == ".wav":
        return "wav"
    if suffix == ".mp3":
        return "mp3"
    return None


def _assert_pcm_wav(data: bytes) -> None:
    """Require 16-bit PCM WAV (mono or stereo)."""
    if len(data) < 12 or data[0:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise HoldAudioError("File is not a WAV (expected RIFF/WAVE header)")
    try:
        with wave.open(BytesIO(data), "rb") as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            frame_rate = wf.getframerate()
            nframes = wf.getnframes()
    except wave.Error as exc:
        raise HoldAudioError(f"Invalid WAV file: {exc}") from exc

    if channels not in (1, 2):
        raise HoldAudioError("Hold audio WAV must be mono or stereo")
    if sample_width != 2:
        raise HoldAudioError("Hold audio WAV must be 16-bit PCM")
    if frame_rate <= 0 or nframes <= 0:
        raise HoldAudioError("Hold audio WAV has no audio frames")


def _assert_mp3(data: bytes) -> None:
    """Decode with miniaudio to prove the MP3 is playable."""
    try:
        import miniaudio
    except ImportError as exc:
        raise HoldAudioError("MP3 support is unavailable on this server") from exc

    try:
        info = miniaudio.mp3_get_info(data)
    except Exception as exc:
        raise HoldAudioError(f"Invalid MP3 file: {exc}") from exc

    channels = int(getattr(info, "nchannels", 0) or 0)
    sample_rate = int(getattr(info, "sample_rate", 0) or 0)
    num_frames = int(getattr(info, "num_frames", 0) or 0)
    if channels not in (1, 2):
        raise HoldAudioError("Hold audio MP3 must be mono or stereo")
    if sample_rate <= 0 or num_frames <= 0:
        raise HoldAudioError("Hold audio MP3 has no audio frames")


def validate_upload(filename: str | None, data: bytes) -> tuple[str, HoldAudioFormat]:
    """Validate filename + bytes; return safe basename and format."""
    if not filename:
        raise HoldAudioError("Only WAV and MP3 files are allowed")
    fmt = _extension_format(filename)
    if fmt is None or Path(filename).suffix.lower() not in _ALLOWED_EXTENSIONS:
        raise HoldAudioError("Only WAV and MP3 files are allowed")
    if not data:
        raise HoldAudioError("Empty file")
    max_bytes = settings.HOLD_AUDIO_MAX_UPLOAD_BYTES
    if len(data) > max_bytes:
        raise HoldAudioError(
            f"File too large (max {max_bytes // (1024 * 1024)} MB)"
        )
    if fmt == "wav":
        _assert_pcm_wav(data)
    else:
        _assert_mp3(data)
    return Path(filename).name or f"hold.{fmt}", fmt


def upload_clip(org_id: str, filename: str, data: bytes) -> dict[str, str]:
    """Store a validated WAV/MP3 and return clip metadata."""
    safe_name, fmt = validate_upload(filename, data)
    clip_id = str(uuid.uuid4())
    key = storage_key_for(org_id, clip_id, safe_name)

    from app.storage.minio_client import MinIOStorage

    storage = MinIOStorage()
    storage.client.put_object(
        settings.MINIO_BUCKET,
        key,
        BytesIO(data),
        length=len(data),
        content_type=_CONTENT_TYPES[fmt],
    )
    return {
        "clip_id": clip_id,
        "storage_key": key,
        "filename": safe_name,
    }


# Back-compat alias used by older call sites / docs.
upload_wav = upload_clip


def delete_clip(org_id: str, clip_id: str, storage_key: str) -> None:
    """Delete a hold clip if the key belongs to this org and clip_id."""
    assert_org_storage_key(org_id, storage_key)
    expected_prefix = f"{HOLD_AUDIO_PREFIX}/{org_id}/{clip_id}/"
    if not storage_key.startswith(expected_prefix):
        raise HoldAudioError("storage_key does not match clip_id for this organisation")

    from app.storage.minio_client import MinIOStorage

    storage = MinIOStorage()
    try:
        storage.client.remove_object(settings.MINIO_BUCKET, storage_key)
    except Exception as exc:
        logger.warning("Failed to delete hold-audio object %s: %s", storage_key, exc)
        raise HoldAudioError("Failed to delete hold-audio object") from exc


def validate_behaviour_clips(org_id: str, clips: list[Any]) -> None:
    """Ensure every clip key is org-scoped and clip count is within limits."""
    max_clips = settings.HOLD_AUDIO_MAX_CLIPS
    if len(clips) > max_clips:
        raise HoldAudioError(
            f"hold_audio_clips may contain at most {max_clips} clips"
        )
    seen: set[str] = set()
    for clip in clips:
        if isinstance(clip, dict):
            clip_id = str(clip.get("clip_id") or "").strip()
            storage_key = str(clip.get("storage_key") or "").strip()
            filename = str(clip.get("filename") or "").strip()
        else:
            clip_id = str(getattr(clip, "clip_id", "") or "").strip()
            storage_key = str(getattr(clip, "storage_key", "") or "").strip()
            filename = str(getattr(clip, "filename", "") or "").strip()
        if not clip_id or not storage_key or not filename:
            raise HoldAudioError(
                "hold_audio_clips entries require clip_id, storage_key, and filename"
            )
        assert_org_storage_key(org_id, storage_key)
        expected_prefix = f"{HOLD_AUDIO_PREFIX}/{org_id}/{clip_id}/"
        if not storage_key.startswith(expected_prefix):
            raise HoldAudioError(
                "hold_audio_clips.storage_key must include the matching clip_id"
            )
        if clip_id in seen:
            raise HoldAudioError(f"Duplicate hold_audio_clips.clip_id: {clip_id}")
        seen.add(clip_id)
