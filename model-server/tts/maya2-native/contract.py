"""What this slot adds to upstream's OpenAI-compatible server, as pure functions.

Upstream's `maya3.server` already speaks `POST /v1/audio/speech` -- streaming,
admission control, cancellation on disconnect, OpenAI-shaped errors. What it
does not do is follow this repo's slot contract (model-server/README.md, "What
a model folder has to provide"), and every difference is decided here so it can
be tested without a GPU, torch, aiohttp or the maya3 package:

* **`X-Audio-Format` on every speech response.** The client decodes by header,
  never by assumption. Upstream says `X-Encoding: pcm_s16le`; the repo's name for
  that is OpenAI's `pcm`.
* **`response_format` defaults to `pcm`**, not upstream's `wav` (and not
  OpenAI's `mp3`). Every caller in this repo pins `pcm`; a caller that forgets
  gets the slot's native stream rather than a RIFF header in its PCM.
* **`language` accepts VoicEra's canonical ids.** The agent config stores Odia
  as `od`; the model knows it as `or`. Region tags (`hi-IN`) are trimmed.
* **OpenAI fields the model cannot honour are accepted and reported, not
  refused.** `instructions` (no delivery conditioning in this model) and a
  non-unity `speed` (upstream answers 400) are dropped and named in
  `X-Instructions-Ignored` / `X-Speed-Ignored`, the way tts/rumik-oss-1 reports
  speed. An OpenAI SDK call that works against api.openai.com works here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

#: The model's languages, exactly upstream's `maya3.server.LANGS`.
LANGS: tuple[str, ...] = ("as", "bn", "en", "gu", "hi", "kn", "ml", "mr", "or", "pa", "ta", "te")

#: VoicEra canonical id -> the model's code, for the one place they differ.
LANGUAGE_ALIASES: dict[str, str] = {"od": "or"}

#: response_format values upstream can produce, OpenAI's names throughout.
#: `pcm` is signed 16-bit little-endian mono at 24 kHz. `aac` is OpenAI's too,
#: but upstream bundles no encoder and refuses it with a 400 naming the reason.
SPEECH_FORMATS: tuple[str, ...] = ("pcm", "wav", "mp3", "opus", "flac")

#: OpenAI's own voice names. Upstream maps them to its `plain` voice -- a
#: speaker drawn at random per request, which on a phone call sounds like a new
#: person every sentence. Here they mean "the slot's default voice" instead.
OPENAI_VOICES = frozenset(
    {
        "alloy",
        "ash",
        "ballad",
        "coral",
        "echo",
        "fable",
        "onyx",
        "nova",
        "sage",
        "shimmer",
        "verse",
        "marin",
        "cedar",
    }
)

SPEECH_PATH = "/v1/audio/speech"


def wire_language(value: Any) -> Any:
    """Canonical or regional id -> the model's code. Anything unrecognised is
    returned untouched so upstream's 400 names the field and lists the valid ones."""
    if not isinstance(value, str):
        return value
    code = value.strip().lower().replace("_", "-")
    if code in ("", "auto"):
        return code or None
    code = code.split("-", 1)[0]
    code = LANGUAGE_ALIASES.get(code, code)
    return code if code in LANGS else value


def shape_speech_body(body: Mapping[str, Any], default_format: str) -> tuple[dict, dict[str, str]]:
    """Rewrite an OpenAI speech request into what upstream accepts.

    Returns the new body and the extra response headers it implies. The input
    is not modified.
    """
    out = dict(body)
    headers: dict[str, str] = {}

    fmt = out.get("response_format")
    if fmt is None or (isinstance(fmt, str) and not fmt.strip()):
        out["response_format"] = default_format
    elif isinstance(fmt, str):
        out["response_format"] = fmt.strip().lower()

    # `lang` is upstream's alias. When both are given, `language` wins.
    if "language" in out:
        lang = out["language"]
        out.pop("lang", None)
    else:
        lang = out.pop("lang", None)
    lang = wire_language(lang)
    if lang is None:
        out.pop("language", None)  # absent: upstream reads the script
    else:
        out["language"] = lang

    instructions = out.pop("instructions", None)
    if isinstance(instructions, str) and instructions.strip():
        headers["X-Instructions-Ignored"] = "1"

    if "speed" in out:
        speed = out.pop("speed")
        if speed is not None and not (
            isinstance(speed, (int, float)) and not isinstance(speed, bool) and float(speed) == 1.0
        ):
            headers["X-Speed-Ignored"] = str(speed)

    return out, headers


def audio_format_header(response_format: Any) -> str | None:
    """`X-Audio-Format` for a response_format, or None when nothing was sent."""
    if not isinstance(response_format, str):
        return None
    fmt = response_format.strip().lower()
    return fmt if fmt in SPEECH_FORMATS else None


def pick_voice(requested: Any, default_voice: str, registered: Iterable[str]) -> Any:
    """The voice id to hand upstream's resolver.

    Blank and OpenAI's own names become the default voice, unless a voice of
    that name has actually been registered. Anything else passes through, so an
    unknown name still reaches upstream's 400, which lists the real ones.
    """
    if requested is None or (isinstance(requested, str) and not requested.strip()):
        return default_voice
    if not isinstance(requested, str):
        return requested
    name = requested.strip()
    known = {v.lower() for v in registered}
    if name.lower() in OPENAI_VOICES and name.lower() not in known:
        return default_voice
    return name


def voice_languages(meta: Mapping[str, Any] | None) -> list[str]:
    """Languages a named voice was trained on (>= 1 h each, per the model card)."""
    langs = (meta or {}).get("langs") or []
    return [str(x) for x in langs if isinstance(x, str)]


def untrained_language(meta: Mapping[str, Any] | None, lang: Any) -> bool:
    """True when a named voice speaks a language it has no training data in.

    That still produces speech -- the language tag drives the text, the name
    drives the timbre -- but it is cross-lingual, and Assamese is like that for
    every one of the 20 voices. Reported, never refused.
    """
    langs = voice_languages(meta)
    return bool(langs) and isinstance(lang, str) and lang not in langs


def voice_roster(
    voices: Iterable[tuple[str, str, Mapping[str, Any] | None]], default_voice: str
) -> dict:
    """GET /v1/voices in the repo's shape (`{"object": "list", "data": [...]}`).

    `voices` is (id, mode, meta) per registered voice. Upstream's always-present
    `plain` voice is left out: it is a random speaker, not one an agent could be
    configured with and hear again.
    """
    data = []
    for vid, mode, meta in voices:
        if vid == "plain":
            continue
        meta = meta or {}
        entry: dict[str, Any] = {"id": vid, "languages": voice_languages(meta) or list(LANGS)}
        for key, src in (("gender", "gender"), ("age", "age_band"), ("description", "description")):
            if meta.get(src):
                entry[key] = meta[src]
        if mode != "named":
            entry["mode"] = mode
        data.append(entry)
    return {"object": "list", "data": data, "default": default_voice}
