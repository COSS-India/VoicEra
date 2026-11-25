"""Redact PII from transcript text before it is stored.

Pattern-based and dependency-free. Indic digits (Devanagari, Bengali, Gujarati,
Tamil, Telugu, Kannada, Malayalam, Gurmukhi, Odia) and Arabic-Indic digits (Arabic,
Urdu/Persian) are matched like ASCII digits.

Redaction is irreversible, so ambiguity resolves toward leaving text alone. Digits
may be written together ("9876543210"), one digit at a time ("9 8 7 6 ..."), or in
the grouping each identifier is actually read out in (phone 5-5, Aadhaar 4-4-4,
card 4-4-4-4 / 4-6-5). Anything else, such as several prices in a row
("2400 2500 2600"), is treated as separate numbers and left alone. Aadhaar numbers
must also pass the Verhoeff checksum and cards the Luhn checksum.

Controlled by two environment variables, read on every call:

- ``PII_REDACTION_ENABLED``: ``true`` to redact. Default ``false``.
- ``PII_REDACTION_ENTITIES``: comma-separated subset of ``ENTITIES``. Default: all.

Known limits: numbers spoken as words ("nine eight seven..."), names and postal
addresses are not detected.
"""

from __future__ import annotations

import os
import re

# Order is precedence: when two matches overlap, the earlier entity wins.
ENTITIES: tuple[str, ...] = ("EMAIL", "CARD", "PAN", "PHONE", "AADHAAR", "DOB", "NUMBER")

# A single space or hyphen. The backreference \1 / \2 in the grouped forms below
# makes every gap in one identifier use the same separator.
_SEP = r"[ -]"


def _spelled(first: str, rest: int | str) -> str:
    """``first`` digit then ``rest`` more, every digit separated: "9 8 7 6 ...".

    Must not start or end inside a longer separated run, so a twelve-digit
    Aadhaar read out digit by digit is not also matched as a ten-digit phone.
    """
    return rf"(?<!\d{_SEP}){first}(?:{_SEP}\d){{{rest}}}(?!{_SEP}\d)"


_PATTERNS: dict[str, re.Pattern[str]] = {
    "EMAIL": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"),
    # 13-19 digits together, 4-4-4-4, 4-6-5, or one digit at a time; Luhn-checked.
    "CARD": re.compile(
        rf"(?<!\d)(?:\d{{13,19}}"
        rf"|\d{{4}}({_SEP})\d{{4}}\1\d{{4}}\1\d{{4}}"
        rf"|\d{{4}}({_SEP})\d{{6}}\2\d{{5}}"
        rf"|{_spelled(r'\d', '12,18')})(?!\d)"
    ),
    "PAN": re.compile(r"\b[A-Za-z]{5}\d{4}[A-Za-z]\b"),
    # Indian mobile: optional +91 or 0, then ten digits starting 6-9, written
    # together, as 5-5, or one digit at a time.
    "PHONE": re.compile(
        rf"(?<!\d)(?:\+91{_SEP}?|0)?"
        rf"(?:[6-9]\d{{9}}|[6-9]\d{{4}}{_SEP}\d{{5}}|{_spelled('[6-9]', 9)})(?!\d)"
    ),
    # Twelve digits together, 4-4-4, or one digit at a time; Verhoeff-checked.
    "AADHAAR": re.compile(
        rf"(?<!\d)(?:[2-9]\d{{11}}|[2-9]\d{{3}}({_SEP})\d{{4}}\1\d{{4}}|{_spelled('[2-9]', 11)})(?!\d)"
    ),
    "DOB": re.compile(
        r"(?<!\d)(?:0?[1-9]|[12]\d|3[01])[/.-](?:0?[1-9]|1[0-2])[/.-](?:19|20)\d{2}(?!\d)"
    ),
    # Catch-all for account numbers and other long IDs: nine or more digits,
    # written together or one digit at a time.
    "NUMBER": re.compile(rf"(?<!\d)(?:\d{{9,}}|{_spelled(r'\d', '8,')})(?!\d)"),
}

_INDIC_ZEROS = (
    0x0660,  # Arabic-Indic
    0x06F0,  # Extended Arabic-Indic (Urdu, Persian)
    0x0966,  # Devanagari
    0x09E6,  # Bengali
    0x0A66,  # Gurmukhi
    0x0AE6,  # Gujarati
    0x0B66,  # Odia
    0x0BE6,  # Tamil
    0x0C66,  # Telugu
    0x0CE6,  # Kannada
    0x0D66,  # Malayalam
)
_DIGIT_MAP = {zero + i: str(i) for zero in _INDIC_ZEROS for i in range(10)}


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_enabled() -> bool:
    return _truthy(os.getenv("PII_REDACTION_ENABLED"))


def enabled_entities() -> tuple[str, ...]:
    raw = (os.getenv("PII_REDACTION_ENTITIES") or "").strip()
    if not raw:
        return ENTITIES
    wanted = {item.strip().upper() for item in raw.split(",") if item.strip()}
    return tuple(entity for entity in ENTITIES if entity in wanted)


def _luhn_ok(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)


def _verhoeff_ok(digits: str) -> bool:
    """Aadhaar's last digit is a Verhoeff check digit."""
    check = 0
    for index, char in enumerate(reversed(digits)):
        check = _VERHOEFF_D[check][_VERHOEFF_P[index % 8][int(char)]]
    return check == 0


def redact_text(text: str, entities: tuple[str, ...] | None = None) -> str:
    """Return ``text`` with every detected entity replaced by ``[REDACTED_<ENTITY>]``."""
    if not text:
        return text

    # One-to-one digit mapping, so match offsets are valid for the original text.
    normalized = text.translate(_DIGIT_MAP)
    spans: list[tuple[int, int, str]] = []

    for entity in ENTITIES if entities is None else entities:
        for match in _PATTERNS[entity].finditer(normalized):
            start, end = match.span()
            digits = re.sub(r"\D", "", match.group())
            if entity == "CARD" and not _luhn_ok(digits):
                continue
            if entity == "AADHAAR" and not _verhoeff_ok(digits):
                continue
            if any(start < taken_end and taken_start < end for taken_start, taken_end, _ in spans):
                continue
            spans.append((start, end, entity))

    for start, end, entity in sorted(spans, reverse=True):
        text = f"{text[:start]}[REDACTED_{entity}]{text[end:]}"
    return text


def redact_if_enabled(text: str) -> str:
    """Redact ``text`` when ``PII_REDACTION_ENABLED`` is set; otherwise return it unchanged."""
    if not is_enabled():
        return text
    return redact_text(text, enabled_entities())
