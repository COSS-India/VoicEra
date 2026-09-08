"""Canonical language ids used across all providers.

Keys are what we store in the DB and what the user selects in the UI.
They are stable, provider-agnostic ids.

Each vendor folder maps these ids to its own codes in ``catalog.py``
(``STT_CAPABILITIES`` / ``TTS_CAPABILITIES``).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

# Canonical language id -> human-readable label
LANGUAGES: dict[str, str] = {
    # --- Auto-detect ---
    "multi": "Indian Multilingual",

    # --- Indian languages ---
    "hi": "Hindi",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "gu": "Gujarati",
    "kn": "Kannada",
    "ml": "Malayalam",
    "mr": "Marathi",
    "pa": "Punjabi",
    "od": "Odia",
    "as": "Assamese",
    "ur": "Urdu",
    "ne": "Nepali",
    "sa": "Sanskrit",
    "brx": "Bodo",
    "doi": "Dogri",
    "kok": "Konkani",
    "ks": "Kashmiri",
    "mai": "Maithili",
    "mni": "Manipuri",
    "sat": "Santali",
    "sd": "Sindhi",
    "bh": "Bhili",
    "bho": "Bhojpuri",
    "bgc": "Haryanvi",
    "hne": "Chhattisgarhi",

    # --- English variants ---
    "en": "English",
    "en-US": "English (United States)",
    "en-GB": "English (United Kingdom)",
    "en-AU": "English (Australia)",
    "en-CA": "English (Canada)",
    "en-NZ": "English (New Zealand)",
    "en-HK": "English (Hong Kong)",
    "en-IE": "English (Ireland)",
    "en-PH": "English (Philippines)",
    "en-PK": "English (Pakistan)",
    "en-SG": "English (Singapore)",
}


class UnknownLanguageError(ValueError):
    """Raised when a language id is not in the canonical ``LANGUAGES`` map."""

    def __init__(self, unknown: Sequence[str]) -> None:
        self.unknown = tuple(unknown)
        listed = ", ".join(self.unknown)
        super().__init__(f"Unknown language id(s): {listed}")


def label(lang_id: str) -> str:
    """Return a human-readable label for a canonical language id."""
    return LANGUAGES.get(lang_id, lang_id)


def ids() -> tuple[str, ...]:
    """All canonical language ids."""
    return tuple(LANGUAGES.keys())


def canonical_languages() -> dict[str, str]:
    """Copy of the canonical language id → label map."""
    return dict(LANGUAGES)


def parse_language_ids(
    languages: str | Sequence[str] | None = None,
) -> tuple[str, ...]:
    """Parse and validate canonical language ids.

    Accepts a comma-separated string, a sequence, or ``None`` / empty
    (meaning “no filter”). Unknown ids raise ``UnknownLanguageError``.
    """
    if languages is None:
        return ()
    if isinstance(languages, str):
        parts = [part.strip() for part in languages.split(",")]
    else:
        parts = [str(part).strip() for part in languages]
    parsed = tuple(part for part in parts if part)
    unknown = [lang_id for lang_id in parsed if lang_id not in LANGUAGES]
    if unknown:
        raise UnknownLanguageError(unknown)
    return parsed


def language_schema_extra(
    supported: dict[str, dict[str, str]],
    *,
    allow_custom_input: bool = True,
) -> dict[str, Any]:
    """Build ``json_schema_extra`` for a config ``language`` field.

    ``supported`` is the per-model map from vendor capabilities::

        model_id -> {vendor_code: canonical_id}

    The returned extras ride along with ``model_json_schema()`` so the API
    gets languages from the same dump as the rest of the config:

    - ``examples`` — flat sorted unique canonical ids
    - ``model_options`` — model → sorted canonical ids (UI filters by model)
    - ``language_codes`` — model → {canonical_id: vendor_code} (wire to vendor)
    - ``allow_custom_input`` — when True, UI may accept values outside examples
    """
    model_options: dict[str, list[str]] = {}
    language_codes: dict[str, dict[str, str]] = {}
    all_canonical: set[str] = set()

    for model, mapping in supported.items():
        canonicals = sorted(set(mapping.values()))
        model_options[model] = canonicals
        all_canonical.update(canonicals)

        # Invert vendor→canonical to canonical→vendor (first vendor wins).
        inverted: dict[str, str] = {}
        for vendor_code, canonical in mapping.items():
            inverted.setdefault(canonical, vendor_code)
        language_codes[model] = dict(sorted(inverted.items()))

    extra: dict[str, Any] = {
        "examples": sorted(all_canonical),
        "model_options": model_options,
        "language_codes": language_codes,
    }
    if allow_custom_input:
        extra["allow_custom_input"] = True
    return extra
