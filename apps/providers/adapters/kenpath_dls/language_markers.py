"""Parse and strip Vistaar DLS ``<lang:…>`` voice markers."""

from __future__ import annotations

import re

# Sent once at the start of the turn where language is decided.
_LANG_MARKER = re.compile(r"<lang:([a-zA-Z0-9_-]+)>", re.IGNORECASE)

# Hold trailing bytes that may be an incomplete marker across stream chunks.
_HOLD_TAIL = re.compile(
    r"(?:<(?:l(?:a(?:n(?:g(?::[a-zA-Z0-9_-]*)?)?)?)?)?)$",
    re.IGNORECASE,
)

# Wire codes from DLS → VoicEra canonical language ids.
_WIRE_TO_CANONICAL: dict[str, str] = {
    "mr": "mr",
    "bhb": "bh",
}


def wire_to_canonical(wire: str) -> str:
    """Map a DLS wire language code to a VoicEra canonical id."""
    key = (wire or "").strip().lower()
    return _WIRE_TO_CANONICAL.get(key, key)


def extract_lang_marker(text: str) -> str | None:
    """Return the first wire language code in ``text``, if any."""
    match = _LANG_MARKER.search(text or "")
    if not match:
        return None
    return match.group(1).lower()


def strip_lang_marker_for_tts(text: str) -> str:
    """Remove complete ``<lang:…>`` markers so TTS never speaks them."""
    if not text:
        return ""
    trailing_space = text.endswith(" ")
    stripped = _LANG_MARKER.sub("", text)
    stripped = " ".join(stripped.split())
    if stripped and trailing_space:
        return stripped + " "
    return stripped


def flush_speakable(buffer: str) -> tuple[str, str]:
    """Split ``buffer`` into speakable text and a held incomplete marker prefix."""
    match = _HOLD_TAIL.search(buffer)
    if match:
        return buffer[: match.start()], buffer[match.start() :]
    return buffer, ""
