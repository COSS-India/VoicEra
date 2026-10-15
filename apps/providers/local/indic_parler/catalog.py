"""Indic Parler TTS model catalog (model-server ``tts/indic-parler`` slot).

Three things here are unlike ``indic_orpheus`` and ``rumik_oss``, and all three
are the model's doing:

**44.1 kHz, not 24 kHz.** Parler's DAC vocoder runs at 44100 Hz. The engine's
native wire is float32; this provider asks for ``pcm`` (signed 16-bit), which
the server converts to, so Pipecat can push the bytes without decoding.

**The voice is a description, and a speaker name is optional.** The server
joins ``voice`` and ``instructions`` into one prompt -- ``"{voice}. {style}"``
-- and ignores ``language``; the model reads the language from the script of
the text. A named speaker is just a word the model was trained to associate
with a voice, so it helps where the model card names one and is not needed
where it does not.

**Named speakers exist for some languages and not others.** The roster below is
the model card's (ai4bharat/indic-parler-tts, "Speaker" table), checked
against the identical one already in ``adapters/bhashini/catalog.py``. Where the
card names no speaker, ``voice`` is a free-text field defaulting to empty, and
``style`` alone conditions the voice.
"""

from __future__ import annotations

import os

SAMPLE_RATE = 44100

# Slot id from model-server GET /v1/models -- the folder under
# model-server/tts/. The model id is kept equal to it, as rumik_oss does.
GATEWAY_MODEL_ID = "indic-parler"
TTS_MODEL = "indic-parler"

# models.yaml names Divya as this slot's preset.
DEFAULT_TTS_VOICE = "Divya"

# Vendor language code -> (VoicEra canonical id, speakers, recommended first).
#
# The language list is the union of models.yaml's 23 for this slot and the two
# the model card adds: English (officially supported, 21 speakers) and
# Chhattisgarhi (``hne``, listed by the card as unofficial). The card also calls
# Kashmiri and Punjabi unofficial; they are in models.yaml, so they are here.
#
# BHILI (``bhb``/``bh``) has no speakers of its own on the card. It is written
# in Devanagari and the model reads the language from the script, so it is
# offered with the Marathi speakers -- the same choice the Bhashini adapter
# makes for its Parler Bhili. Expect a Marathi-accented read, not native Bhili.
_TTS_LANGS: dict[str, tuple[str, tuple[str, ...]]] = {
    "as": ("as", ("Amit", "Sita", "Poonam", "Rakesh")),
    "bn": ("bn", ("Arjun", "Aditi", "Tapan", "Rashmi", "Arnav", "Riya")),
    "brx": ("brx", ("Bikram", "Maya", "Kalpana")),
    "hne": ("hne", ("Bhanu", "Champa")),
    "doi": ("doi", ("Karan",)),
    "en": (
        "en",
        (
            "Thoma", "Mary", "Swapna", "Dinesh", "Meera", "Jatin", "Aakash",
            "Sneha", "Kabir", "Tisha", "Chingkhei", "Thoiba", "Priya", "Tarun",
            "Gauri", "Nisha", "Raghav", "Kavya", "Ravi", "Vikas", "Riya",
        ),
    ),
    "gu": ("gu", ("Yash", "Neha")),
    "hi": ("hi", ("Rohit", "Divya", "Aman", "Rani")),
    "kn": ("kn", ("Suresh", "Anu", "Chetan", "Vidya")),
    "ml": ("ml", ("Anjali", "Harish", "Anju")),
    "mni": ("mni", ("Laishram", "Ranjit")),
    "mr": ("mr", ("Sanjay", "Sunita", "Nikhil", "Radha", "Varun", "Isha")),
    "bhb": ("bh", ("Sanjay", "Sunita", "Nikhil", "Radha", "Varun", "Isha")),
    "ne": ("ne", ("Amrita",)),
    "or": ("od", ("Manas", "Debjani")),
    "pa": ("pa", ("Divjot", "Gurpreet")),
    "sa": ("sa", ("Aryan",)),
    "ta": ("ta", ("Jaya", "Kavitha")),
    "te": ("te", ("Prakash", "Lalitha", "Kiran")),
    # No named speakers on the model card: description only.
    "kok": ("kok", ()),
    "ks": ("ks", ()),
    "mai": ("mai", ()),
    "sat": ("sat", ()),
    "sd": ("sd", ()),
    "ur": ("ur", ()),
}

# Voice descriptions, from the same set the Bhashini adapter's Parler uses (the
# model card's own prompt style), minus the one that asks for an American
# accent -- wrong for every language here. Free text: these are a starting
# point and an operator may write their own. No speaker name in any of them;
# the server prepends ``voice``.
TTS_STYLES: tuple[str, ...] = (
    "Slightly higher-pitched, expressive voice in a close-sounding environment. The voice is clear, with subtle emotional depth and a normal pace, captured in high-quality recording.",
    "Fast-paced speech with a slightly low-pitched voice, captured clearly in a close-sounding environment with excellent recording quality.",
    "Male voice speaking at a moderate pace with a slightly monotone tone. The recording is clear, with a close sound and only minimal ambient noise.",
    "High-pitched voice in a close environment. The voice is clear, with slight dynamic changes, and the recording is of excellent quality.",
    "High-pitched, engaging voice captured in a clear, close-sounding recording. A slightly slower delivery conveys a positive tone.",
    "High-pitched voice speaking at a slow pace. The voice is clear, with excellent recording quality and only moderate background noise.",
    "Slow speech with a high pitch and expressive tone. The recording is clear, showcasing an energetic and emotive voice.",
    "High-pitched voice with a fast pace, conveying urgency. The recording is clear and intimate, with great emotional depth.",
    "High-pitched voice speaking at a normal pace in a clear, close-sounding environment. The neutral tone is captured with excellent audio quality.",
)

DEFAULT_TTS_STYLE = TTS_STYLES[0]


def _voice_meta(speakers: tuple[str, ...]) -> dict:
    if not speakers:
        return {
            "default": "",
            "options": [],
            "input_type": "input",
            "description": (
                "The model card names no speaker for this language. Leave empty to "
                "let the style description alone set the voice, or type a name."
            ),
        }
    return {
        "default": DEFAULT_TTS_VOICE if DEFAULT_TTS_VOICE in speakers else speakers[0],
        "options": list(speakers),
        "input_type": "dropdown",
        "description": (
            "Speaker name, prepended to the style description. It does not select "
            "the language -- the model reads that from the text's script."
        ),
    }


def _style_meta() -> dict:
    return {
        "default": DEFAULT_TTS_STYLE,
        "options": list(TTS_STYLES),
        "input_type": "both",
        "allow_custom_input": True,
        "description": (
            "Free-text voice description sent as OpenAI TTS instructions: pitch, "
            "pace, tone, recording quality. These are a starting point."
        ),
    }


def _tts_settings() -> dict[str, dict]:
    return {
        vendor: {"voice": _voice_meta(speakers), "style": _style_meta()}
        for vendor, (_canonical, speakers) in _TTS_LANGS.items()
    }


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
