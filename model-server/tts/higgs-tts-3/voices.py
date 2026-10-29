"""The named voices: a roster over reference clips.

Higgs TTS 3 has no built-in speakers. Every voice is zero-shot cloned from a
reference clip on each request, so a "voice" here is a manifest entry naming a
clip in voices/refs/ and, ideally, its transcript. Boson's cookbook says the
transcript "materially improves cloning quality", which is why the manifest
carries `text` and why scripts/fetch_voices.py never trims a clip -- a trimmed
clip no longer matches its transcript.

The clips are read by the SIDECAR, not by this process: the adapter sends a path
under the sidecar's --allowed-local-media-path, and SGLang-Omni encodes the clip
(and caches the encoded prompt by fingerprint). This process only checks that
the file exists, so a missing clip is a clear 503 naming the voice and the
script that fetches it, not a sidecar error about a path.

manifest.json:

    {"default": "Aditi",
     "voices": [{"name": "Aditi", "gender": "female", "language": "hi",
                 "ref": "aditi.wav", "text": "<transcript>", "source": "..."}]}
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("higgs.voices")


@dataclass(frozen=True)
class Voice:
    name: str
    ref: str
    text: str
    gender: str
    language: str
    source: str
    #: True when the clip is on disk. A voice can be catalogued before its clip
    #: has been fetched; it is listed, but refused until then.
    available: bool


class VoiceError(LookupError):
    """A voice that does not exist, or exists without its clip."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status


class Roster:
    def __init__(self, voices: list[Voice], default: str) -> None:
        self.voices = voices
        self.default = default
        self._by_key = {v.name.casefold(): v for v in voices}

    @classmethod
    def load(cls, voices_dir: str | Path) -> Roster:
        root = Path(voices_dir)
        manifest = root / "manifest.json"
        if not manifest.is_file():
            log.warning("no voice manifest at %s; the roster is empty", manifest)
            return cls([], "")
        raw = json.loads(manifest.read_text(encoding="utf-8"))
        voices = []
        for entry in raw.get("voices", []):
            name, ref = entry.get("name"), entry.get("ref")
            if not name or not ref:
                raise ValueError(f"{manifest}: every voice needs `name` and `ref`: {entry}")
            available = (root / "refs" / ref).is_file()
            text = (entry.get("text") or "").strip()
            if available and not text:
                log.warning("voice %s has no transcript; cloning will be weaker", name)
            voices.append(Voice(
                name=name, ref=ref, text=text, gender=entry.get("gender", ""),
                language=entry.get("language", ""), source=entry.get("source", ""),
                available=available,
            ))
        roster = cls(voices, raw.get("default", voices[0].name if voices else ""))
        log.info("voices: %s", ", ".join(
            f"{v.name}{'' if v.available else ' (no clip)'}" for v in voices) or "none")
        return roster

    @property
    def available(self) -> list[Voice]:
        return [v for v in self.voices if v.available]

    def resolve(self, name: str) -> Voice:
        voice = self._by_key.get(name.strip().casefold())
        if voice is None:
            known = ", ".join(v.name for v in self.voices) or "none"
            raise VoiceError(f"unknown voice {name!r}; this server has: {known}", 400)
        if not voice.available:
            raise VoiceError(
                f"voice {voice.name!r} has no reference clip yet (voices/refs/{voice.ref}). "
                f"Fetch it with scripts/fetch_voices.py -- see voices/README.md",
                503,
            )
        return voice
