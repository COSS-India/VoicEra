"""Parse agent behaviour into typed hold clips and enable gates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

HoldMode = Literal["text", "audio"]


@dataclass(frozen=True, slots=True)
class TextHoldClip:
    text: str


@dataclass(frozen=True, slots=True)
class AudioHoldClip:
    clip_id: str
    storage_key: str
    filename: str
    pcm: bytes | None = None
    sample_rate: int | None = None


HoldClip = TextHoldClip | AudioHoldClip


@dataclass(frozen=True, slots=True)
class HoldConfig:
    mode: HoldMode
    timeout_seconds: float
    clips: tuple[HoldClip, ...]


def _parse_timeout(behaviour: dict[str, Any]) -> float | None:
    timeout_raw = behaviour.get("hold_message_timeout_seconds")
    if timeout_raw is None:
        return None
    timeout_seconds = float(timeout_raw)
    if timeout_seconds <= 0:
        return None
    return timeout_seconds


def _parse_mode(behaviour: dict[str, Any]) -> HoldMode:
    raw = str(behaviour.get("hold_mode") or "text").strip().lower()
    return "audio" if raw == "audio" else "text"


def _parse_text_clips(behaviour: dict[str, Any]) -> tuple[TextHoldClip, ...]:
    raw_messages = behaviour.get("hold_messages") or []
    messages = [str(m).strip() for m in raw_messages if str(m).strip()]
    return tuple(TextHoldClip(text=m) for m in messages)


def _parse_audio_clips(behaviour: dict[str, Any]) -> tuple[AudioHoldClip, ...]:
    raw = behaviour.get("hold_audio_clips") or []
    clips: list[AudioHoldClip] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        clip_id = str(item.get("clip_id") or "").strip()
        storage_key = str(item.get("storage_key") or "").strip()
        filename = str(item.get("filename") or "").strip()
        if not clip_id or not storage_key or not filename:
            continue
        clips.append(
            AudioHoldClip(
                clip_id=clip_id,
                storage_key=storage_key,
                filename=filename,
            )
        )
    return tuple(clips)


def hold_config_from_behaviour(behaviour: dict[str, Any]) -> HoldConfig | None:
    """Return a hold config when timeout and active-mode clips are present."""
    timeout_seconds = _parse_timeout(behaviour)
    if timeout_seconds is None:
        return None

    mode = _parse_mode(behaviour)
    if mode == "audio":
        clips: tuple[HoldClip, ...] = _parse_audio_clips(behaviour)
    else:
        clips = _parse_text_clips(behaviour)

    if not clips:
        return None

    return HoldConfig(mode=mode, timeout_seconds=timeout_seconds, clips=clips)


def org_storage_prefix(org_id: str) -> str:
    return f"hold-audio/{org_id}/"


def assert_org_owned_key(org_id: str, storage_key: str) -> bool:
    prefix = org_storage_prefix(org_id)
    key = (storage_key or "").strip()
    if not key.startswith(prefix):
        return False
    remainder = key[len(prefix) :]
    return bool(remainder) and ".." not in remainder.split("/")
