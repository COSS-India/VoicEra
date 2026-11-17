"""Rumik OSS-1 TTS model catalog (model-server ``tts/rumik-oss-1`` slot).

**Licence: CC-BY-NC-4.0 with an acceptable-use addendum — research and
non-commercial use only.** A commercial deployment needs separate permission
from Rumik. This is the only model in the catalogue with that restriction; see
``model-server/tts/rumik-oss-1/README.md``.

Two things here are unlike ``indic_orpheus``, and both are the model's doing:

**A voice does not select a language.** Orpheus's roster assigns every speaker
to exactly one language, so ``voice`` and ``language`` are not independent
there. All four Rumik voices cover all 22 languages, so the roster below is the
same four names under every language and ``language`` carries the script.

**The style is free text, not a roster entry.** Orpheus has a fixed vocabulary
of styles and rejects anything else. Rumik conditions on a natural-language
``<description="...">`` prefix, so ``style`` is ``input_type: "both"`` — the
options are a starting point, and an operator may type their own.
"""

from __future__ import annotations

import os

SAMPLE_RATE = 24000

# Slot id from model-server GET /v1/models (not the inference model name).
# The gateway reports whatever TTS_MODEL names, which is the folder under
# model-server/tts/ -- so this is the folder id.
GATEWAY_MODEL_ID = "rumik-oss-1"
# The inference model name the server reports and accepts. RUMIK_MODEL_NAME
# keeps it equal to the folder id on purpose; the folder's compose.extra.yml
# says why three spellings of one model is how a deployment ends up healthy and
# unreachable.
TTS_MODEL = "rumik-oss-1"

TTS_VOICES: tuple[str, ...] = ("Ira", "Aisha", "Siya", "Zoya")
DEFAULT_TTS_VOICE = "Ira"

# Vendor language code -> (VoicEra canonical id, the accent word the model was
# shown for it). Vendor codes and spellings are taken from the checkpoint's own
# benchmarks/wer-reported-scores.json, so `or` -> `od` exactly as Orpheus maps
# it, and the accent words are the ones used in samples/showcase/manifest.json
# ("Hindi accent", "Telugu accent", "Indian English accent").
#
# WHY 21 INDIC LANGUAGES AND NOT 22. The model card claims "22 Indic languages
# ... plus English" but never enumerates them. What Rumik actually publishes is
# WER and CER for the 21 below. Those 21 are the Eighth Schedule languages with
# exactly one absent -- Sindhi -- so the unaccounted-for 22nd is almost
# certainly `sd`/`sd`, "Sindhi". Almost certainly is not evidence, and the two
# ways of being wrong are not symmetrical: leaving a supported language out
# means an operator cannot select it, while putting an unsupported one in means
# an agent is configured for it and callers hear nonsense with nothing logged.
# So it is left out until Rumik publishes a roster or someone tests it, at which
# point it is one line here.
_TTS_LANGS: dict[str, tuple[str, str]] = {
    "as": ("as", "Assamese"),
    "bn": ("bn", "Bengali"),
    "brx": ("brx", "Bodo"),
    "doi": ("doi", "Dogri"),
    "gu": ("gu", "Gujarati"),
    "hi": ("hi", "Hindi"),
    "kn": ("kn", "Kannada"),
    "kok": ("kok", "Konkani"),
    "ks": ("ks", "Kashmiri"),
    "mai": ("mai", "Maithili"),
    "ml": ("ml", "Malayalam"),
    "mni": ("mni", "Manipuri"),
    "mr": ("mr", "Marathi"),
    "ne": ("ne", "Nepali"),
    "or": ("od", "Odia"),
    "pa": ("pa", "Punjabi"),
    "sa": ("sa", "Sanskrit"),
    "sat": ("sat", "Santali"),
    "ta": ("ta", "Tamil"),
    "te": ("te", "Telugu"),
    "ur": ("ur", "Urdu"),
    "en": ("en", "Indian English"),
}

# (emotion, pace) pairs. Every one of these words is taken from the checkpoint's
# own samples/showcase/manifest.json rather than invented, and each emotion is
# paired with the pace that manifest pairs it with. The model takes free text,
# so this is a starting point and not a vocabulary -- `style` allows custom
# input for exactly that reason.
DELIVERIES: tuple[tuple[str, str], ...] = (
    ("professional", "steady"),
    ("happy", "steady"),
    ("excited", "fast"),
    ("sad", "slow"),
    ("angry", "fast"),
)

#: Accent-free examples for the flat ``style`` field dump. The per-language
#: options below name an accent; a flat list that did would be 105 entries
#: unioned across every language, which is noise in a schema. Dropping the
#: accent clause leaves a string the model still accepts.
TTS_STYLES: tuple[str, ...] = tuple(
    f"{emotion}, {pace} pace" for emotion, pace in DELIVERIES
)

#: Field-level default. Deliberately carries no accent clause: the accent
#: belongs to whichever language the agent is configured for, and the
#: per-language defaults below supply it.
DEFAULT_TTS_STYLE = TTS_STYLES[0]


def _style_options(accent: str) -> list[str]:
    return [f"{emotion}, {accent} accent, {pace} pace" for emotion, pace in DELIVERIES]


def _tts_settings() -> dict[str, dict]:
    settings: dict[str, dict] = {}
    for vendor, (_canonical, accent) in _TTS_LANGS.items():
        options = _style_options(accent)
        settings[vendor] = {
            "voice": {
                "default": DEFAULT_TTS_VOICE,
                "options": list(TTS_VOICES),
                "input_type": "dropdown",
                "description": (
                    "Speaker name. Unlike Orpheus, this does not select the "
                    "language -- every voice covers every language."
                ),
            },
            "style": {
                "default": options[0],
                "options": options,
                "input_type": "both",
                "allow_custom_input": True,
                "description": (
                    "Delivery description, sent as OpenAI TTS instructions and used "
                    "as the model's <description=...> prefix. Emotion, accent and "
                    "pace, comma-separated. Free text -- these are a starting point."
                ),
            },
        }
    return settings


TTS_CAPABILITIES: dict[str, dict] = {
    TTS_MODEL: {
        "languages": {vendor: canonical for vendor, (canonical, _) in _TTS_LANGS.items()},
        "settings": _tts_settings(),
    },
}


def resolve_base_url() -> str:
    """OpenAI speech base URL (must include /v1) — required via Compose ``MODEL_SERVER_URL``."""
    url = (os.getenv("MODEL_SERVER_URL") or "").strip()
    if not url:
        raise RuntimeError("MODEL_SERVER_URL is required (set it in docker-compose)")
    return url
