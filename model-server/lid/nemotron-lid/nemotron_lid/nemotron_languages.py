"""
Language names and wire codes for the 9-language LID probe.
"""

from __future__ import annotations

# Wire codes used in label_mapping.json / probe outputs.
NAME_TO_WIRE: dict[str, str] = {
    "Bengali": "bn",
    "Gujarati": "gu",
    "Hindi": "hi",
    "Kannada": "kn",
    "Malayalam": "ml",
    "Marathi": "mr",
    "Punjabi": "pa",
    "Tamil": "ta",
    "Telugu": "te",
}

WIRE_TO_NAME: dict[str, str] = {v: k for k, v in NAME_TO_WIRE.items()}

APP_LID_LANGS: list[str] = [
    "Bengali",
    "Gujarati",
    "Hindi",
    "Kannada",
    "Malayalam",
    "Marathi",
    "Punjabi",
    "Tamil",
    "Telugu",
]
APP_LID_WIRES: list[str] = [NAME_TO_WIRE[n] for n in APP_LID_LANGS]


def filter_app_lid_langs(langs: list[str]) -> list[str]:
    """Keep only languages in the supported 9-language LID set."""
    app = set(APP_LID_LANGS)
    return [n for n in langs if n in app]
