"""Redact PII from transcript text before it is stored, logged or shown.

Pattern-based and dependency-free. Indic digits (Devanagari, Bengali, Gujarati,
Tamil, Telugu, Kannada, Malayalam, Gurmukhi, Odia) and Arabic-Indic digits (Arabic,
Urdu/Persian) are matched like ASCII digits. Numbers spoken as words ("nine eight
seven ...", "नौ आठ ...", "ಒಂಬತ್ತು ಎಂಟು ...") are read as digits first; see
``number_words``.

Every detected item is replaced with the same placeholder, ``[REDACTED_TEXT]``,
whatever its type. A per-type label ("[REDACTED_PHONE]") would tell anyone
reading the transcript what kind of detail was removed, which helps them guess it
from the surrounding conversation. Types are still detected, because the
checksums, precedence and ``PII_REDACTION_ENTITIES`` depend on them, but they are
never written out.

Redaction is irreversible, so ambiguity resolves toward leaving text alone. Digits
may be written together ("9876543210"), one digit at a time ("9 8 7 6 ..."), in
the grouping each identifier is actually read out in (phone 5-5, Aadhaar 4-4-4,
card 4-4-4-4 / 4-6-5), or, when spoken as words, in pairs ("ninety eight seventy
six ..."). Anything else, such as several prices in a row ("2400 2500 2600"), is
treated as separate numbers and left alone. Aadhaar numbers must also pass the
Verhoeff checksum and cards the Luhn checksum.

Three strengths, one per destination:

- ``stored`` (call transcripts): the rules above. ``redact_turns`` also looks
  across the whole call: a number split over two turns, a part of a number that
  was given in full elsewhere in the call, an OTP given after the agent asked for
  one, and an email given after the agent asked for one.
- ``live`` (browser test panel): ``stored`` per message, plus any run of four or
  more digits read out one at a time or as words, because the panel cannot wait
  for the rest of the call.
- ``log`` (every runtime log line): ``live``, except that long letter-and-digit
  tokens (UUIDs, object IDs, call SIDs) are left intact so logs stay traceable.

Controlled by two environment variables, read on every call:

- ``PII_REDACTION_ENABLED``: ``true`` to redact. Default ``false``.
- ``PII_REDACTION_ENTITIES``: comma-separated subset of ``ENTITIES``. Default: all.

Known limits: names and postal addresses are not detected; romanised Hindi number
words ("ek do teen") and pair-read numbers in languages other than English, Hindi
and Kannada are not read as digits.
"""

from __future__ import annotations

import os
import re
import traceback
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from apps.runtime.services.privacy.number_words import (
    CURRENCY_WORDS,
    UNIT_WORDS,
    WORD_CHAR,
    Normalised,
    Run,
    fold,
    normalise,
)

# Order is precedence: when two matches overlap, the earlier entity wins.
ENTITIES: tuple[str, ...] = ("EMAIL", "CARD", "PAN", "PHONE", "AADHAAR", "DOB", "OTP", "NUMBER")
# The same for every entity, so redacted text does not reveal what was removed.
PLACEHOLDER = "[REDACTED_TEXT]"

Mode = Literal["stored", "live", "log"]

# A single space or hyphen. The backreference \1 / \2 in the grouped forms below
# makes every gap in one identifier use the same separator.
_SEP = r"[ -]"
# Kept outside the f-strings below: Python < 3.12 rejects a backslash inside an
# f-string expression, and the runtime image is python:3.11.
_DIGIT = r"\d"
_NOT_WORD_BEFORE = r"(?<![^\W_])"
_NOT_WORD_AFTER = r"(?![^\W_])"
_INDIC_TAIL = r"[\u0900-\u0d7f\u200c\u200d]*"


def _spelled(first: str, rest: int | str) -> str:
    """``first`` digit then ``rest`` more, every digit separated: "9 8 7 6 ...".

    Must not start or end inside a longer separated run, so a twelve-digit
    Aadhaar read out digit by digit is not also matched as a ten-digit phone.
    """
    return rf"(?<!\d{_SEP}){first}(?:{_SEP}\d){{{rest}}}(?!{_SEP}\d)"


def _alternation(words: Iterable[str]) -> str:
    """Longest first, so "sept" wins over "sep" and "at the rate" over "at"."""
    ordered = sorted(set(words), key=lambda word: (-len(word), word))
    return "(?:" + "|".join(r"\s+".join(map(re.escape, word.split())) for word in ordered) + ")"


# --------------------------------------------------------------------------- #
# Patterns
# --------------------------------------------------------------------------- #

# Word lists are built outside the f-strings: Python 3.11 rejects a backslash
# inside an f-string expression, and some of these words need \u200c.
_DOT_WORD = _alternation(("dot", "period", "डॉट", "डोट", "डाट", "ಡಾಟ್"))
_SEP_WORD = _alternation(("underscore", "hyphen", "dash", "अंडरस्कोर", "ಅಂಡರ್\u200cಸ್ಕೋರ್", "ಅಂಡರ್ಸ್ಕೋರ್"))
_AT_WORD = _alternation(("at", "एट", "ऐट", "ಅಟ್"))
_AT_THE_RATE = _alternation(
    ("at the rate of", "at the rate", "at rate", "एट द रेट", "ऐट द रेट", "ಅಟ್ ದ ರೇಟ್")
)
_TOKEN = rf"(?:{WORD_CHAR}|\d)+"
_DOT = rf"(?:\s*\.\s*|\s+{_DOT_WORD}\s+)"
_LOCAL_SEP = rf"(?:{_DOT}|\s*[_-]\s*|\s+{_SEP_WORD}\s+)"
_AT = rf"(?:\s*@\s*|\s+(?P<rate>{_AT_THE_RATE})\s+|\s+{_AT_WORD}\s+)"
_TLD = _alternation(
    ("com", "in", "org", "net", "co", "gov", "edu", "info", "io", "ai", "world", "biz",
     "me", "us", "uk", "कॉम", "ಕಾಮ್", "इन", "ಇನ್")
)
_SPOKEN_SEPARATOR = re.compile(rf"\s(?:{_DOT_WORD}|{_SEP_WORD})\s", re.IGNORECASE)
_MAIL_PROVIDERS = frozenset(
    ("gmail", "googlemail", "yahoo", "ymail", "outlook", "hotmail", "live", "msn",
     "rediffmail", "rediff", "icloud", "me", "protonmail", "proton", "zoho", "aol")
)

_MONTH = _alternation(
    (
        "january", "february", "march", "april", "may", "june", "july", "august",
        "september", "october", "november", "december", "jan", "feb", "mar", "apr",
        "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
        # Hindi
        "जनवरी", "फरवरी", "फ़रवरी", "मार्च", "अप्रैल", "अप्रेल", "मई", "जून", "जुलाई",
        "अगस्त", "सितंबर", "सितम्बर", "अक्टूबर", "अक्तूबर", "नवंबर", "नवम्बर",
        "दिसंबर", "दिसम्बर",
        # Marathi
        "जानेवारी", "फेब्रुवारी", "एप्रिल", "मे", "जुलै", "ऑगस्ट", "सप्टेंबर",
        "ऑक्टोबर", "नोव्हेंबर", "डिसेंबर",
        # Kannada
        "ಜನವರಿ", "ಫೆಬ್ರವರಿ", "ಫೆಬ್ರುವರಿ", "ಮಾರ್ಚ್", "ಏಪ್ರಿಲ್", "ಮೇ", "ಜೂನ್", "ಜುಲೈ",
        "ಆಗಸ್ಟ್", "ಸೆಪ್ಟೆಂಬರ್", "ಅಕ್ಟೋಬರ್", "ನವೆಂಬರ್", "ಡಿಸೆಂಬರ್",
    )
)
_DAY = r"(?:0?[1-9]|[12]\d|3[01])"
_MONTH_NUMBER = r"(?:0?[1-9]|1[0-2])"
_YEAR = r"(?:19|20)\d{2}"
_ORDINAL = r"(?:st|nd|rd|th|ನೇ|वां|वीं|वी)?"
_DATE_GAP = r"[\s,./-]+"
_MONTH_WORD = rf"{_NOT_WORD_BEFORE}{_MONTH}{_INDIC_TAIL}{_NOT_WORD_AFTER}"

_OTP_KEYWORD = (
    r"(?:\bo\s?t\s?p\b|\bone[\s-]time[\s-](?:password|pin|code)\b|\bverification\s+code\b"
    r"|ओटीपी|ओ\s?टी\s?पी|ಒಟಿಪಿ|ಓಟಿಪಿ|ಒ\s?ಟಿ\s?ಪಿ|ఓటీపీ|ஓடிபி)"
)
_EMAIL_KEYWORD = r"(?:\be-?mail\b|\bmail\s*id\b|ईमेल|इमेल|ई-मेल|ಇಮೇಲ್|ಈಮೇಲ್|ఈమెయిల్|மின்னஞ்சல்)"
_PHONE_KEYWORD = (
    r"(?:\b(?:phone|mobile|number|contact|whats\s?app|call\s+(?:me|on))\b"
    r"|नंबर|नम्बर|मोबाइल|फोन|फ़ोन|व्हाट्सएप|ನಂಬರ್|ಸಂಖ್ಯೆ|ಮೊಬೈಲ್|ಫೋನ್)"
)
_HINTS: dict[str, re.Pattern[str]] = {
    "OTP": re.compile(_OTP_KEYWORD, re.IGNORECASE),
    "EMAIL": re.compile(_EMAIL_KEYWORD, re.IGNORECASE),
    "PHONE": re.compile(_PHONE_KEYWORD, re.IGNORECASE),
}

_EMAIL_TYPED = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_EMAIL_WORDS = re.compile(
    rf"{_NOT_WORD_BEFORE}(?P<local>(?:[a-z0-9] ){{1,29}}[a-z0-9]|{_TOKEN}(?:{_LOCAL_SEP}{_TOKEN}){{0,4}})"
    rf"{_AT}(?P<domain>{_TOKEN}(?:{_DOT}{_TOKEN}){{0,3}}){_DOT}{_TLD}{_NOT_WORD_AFTER}",
    re.IGNORECASE,
)

_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "EMAIL": (_EMAIL_TYPED, _EMAIL_WORDS),
    # 13-19 digits together, 4-4-4-4, 4-6-5, or one digit at a time; Luhn-checked.
    "CARD": (
        re.compile(
            rf"(?<!\d)(?:\d{{13,19}}"
            rf"|\d{{4}}({_SEP})\d{{4}}\1\d{{4}}\1\d{{4}}"
            rf"|\d{{4}}({_SEP})\d{{6}}\2\d{{5}}"
            rf"|{_spelled(_DIGIT, '12,18')})(?!\d)"
        ),
    ),
    "PAN": (
        # Together ("ABCDE1234F"), in groups ("ABCDE 1234 F"), or spelled out one
        # character at a time ("a b c d e 1 2 3 4 f", what speech recognition writes).
        re.compile(r"\b[A-Za-z]{5}\d{4}[A-Za-z]\b"),
        re.compile(rf"{_NOT_WORD_BEFORE}[A-Z]{{5}}{_SEP}\d{{4}}{_SEP}[A-Z]{_NOT_WORD_AFTER}"),
        re.compile(
            rf"{_NOT_WORD_BEFORE}[A-Za-z](?:[ .-][A-Za-z]){{4}}[ .-]\d(?:[ .-]\d){{3}}[ .-][A-Za-z]"
            rf"{_NOT_WORD_AFTER}"
        ),
    ),
    # Indian mobile: optional +91 or 0, then ten digits starting 6-9, written
    # together, as 5-5, or one digit at a time.
    "PHONE": (
        re.compile(
            rf"(?<!\d)(?:\+91{_SEP}?|0)?"
            rf"(?:[6-9]\d{{9}}|[6-9]\d{{4}}{_SEP}\d{{5}}|{_spelled('[6-9]', 9)})(?!\d)"
        ),
    ),
    # Twelve digits together, 4-4-4, or one digit at a time; Verhoeff-checked.
    "AADHAAR": (
        re.compile(
            rf"(?<!\d)(?:[2-9]\d{{11}}|[2-9]\d{{3}}({_SEP})\d{{4}}\1\d{{4}}|{_spelled('[2-9]', 11)})(?!\d)"
        ),
    ),
    "DOB": (
        # 15/12/2021, 15-12-2021, 15.12.2021
        re.compile(rf"(?<!\d){_DAY}[/.-]{_MONTH_NUMBER}[/.-]{_YEAR}(?!\d)"),
        # "15 12 2021": how "fifteen twelve twenty twenty one" reads as digits.
        re.compile(rf"(?<!\d)(?<!\d{_SEP}){_DAY} {_MONTH_NUMBER} {_YEAR}(?!\d)(?!{_SEP}\d)"),
        # 15 December 2021, 15th of December, 2021, 15-Dec-2021, 15 दिसंबर 2021
        re.compile(
            rf"(?<!\d){_DAY}{_ORDINAL}(?:\s+of)?{_DATE_GAP}{_MONTH_WORD}{_DATE_GAP}"
            rf"(?:of\s+)?{_YEAR}(?!\d)",
            re.IGNORECASE,
        ),
        # December 15, 2021
        re.compile(rf"{_MONTH_WORD}{_DATE_GAP}{_DAY}{_ORDINAL},?{_DATE_GAP}{_YEAR}(?!\d)", re.IGNORECASE),
    ),
    # Four to eight digits shortly after "OTP" (only the digits are replaced).
    "OTP": (
        re.compile(
            rf"{_OTP_KEYWORD}[^\d\n]{{0,20}}?(?<!\d)(?P<pii>\d(?:{_SEP}?\d){{3,7}})(?!{_SEP}?\d)",
            re.IGNORECASE,
        ),
    ),
    # Catch-all for account numbers, landlines, partial identifiers and other
    # long IDs: nine or more digits together, or seven or more one at a time.
    "NUMBER": (re.compile(rf"(?<!\d)(?:\d{{9,}}|{_spelled(_DIGIT, '6,')})(?!\d)"),),
}
# live/log only: four or more digits read out one at a time.
_STRICT_NUMBER = re.compile(rf"(?<!\d){_spelled(_DIGIT, '3,')}(?!\d)")
# Letters-and-digits tokens of 12+ characters (UUIDs, object IDs, call SIDs).
_PROTECTED_TOKEN = re.compile(r"(?<![\w-])(?=[\w-]*[A-Za-z])(?=[\w-]*\d)[\w-]{12,}(?![\w-])")
# Digit runs, for the cross-turn rules: one digit at a time, or written together.
_TYPED_RUN = re.compile(r"(?<!\d)(?:\d(?=[ -]\d(?!\d))(?:[ -]\d(?!\d))+|\d{2,})(?!\d)")
_PHONE_DIGITS = re.compile(r"(?:91|0)?[6-9]\d{9}")
# Digits typed in groups ("987 654 3210", "98 76 54 32 10"), one gap between groups.
_GROUPED_RUN = re.compile(r"(?<![\d,.])\d{2,5}(?:[ -]\d{2,5})+(?![\d,.])")
# How a ten-digit mobile is usually written; any other grouping needs a phone hint.
_PHONE_GROUPINGS = frozenset({(5, 5), (3, 3, 4), (4, 3, 3), (2, 2, 2, 2, 2)})
_WORD = re.compile(r"[^\W\d_]+|[\u20b9%]")
_IDENTIFIERS = ("PHONE", "AADHAAR", "CARD", "NUMBER")

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


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #


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


# --------------------------------------------------------------------------- #
# Checksums
# --------------------------------------------------------------------------- #


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


def _identifier(digits: str, wanted: Sequence[str]) -> str | None:
    """Entity for a digit string that is a whole phone, Aadhaar or card number."""
    if "PHONE" in wanted and _PHONE_DIGITS.fullmatch(digits):
        return "PHONE"
    if "AADHAAR" in wanted and len(digits) == 12 and digits[0] in "23456789" and _verhoeff_ok(digits):
        return "AADHAAR"
    if "CARD" in wanted and 13 <= len(digits) <= 19 and _luhn_ok(digits):
        return "CARD"
    return None


# --------------------------------------------------------------------------- #
# Finding spans
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Span:
    start: int
    end: int
    entity: str
    digits: str = ""


@dataclass(frozen=True)
class _DigitRun:
    start: int
    end: int
    digits: str
    read_out: bool  # one digit at a time, or as words: how identifiers are said


@dataclass
class _Found:
    spans: list[_Span]
    runs: list[_DigitRun]


def _hints(*texts: str) -> set[str]:
    return {name for name, pattern in _HINTS.items() if any(pattern.search(t) for t in texts if t)}


def _email_words_ok(match: re.Match[str], hints: set[str]) -> bool:
    """Spoken emails need a sign they are emails, not "look at google dot com"."""
    if match.group("rate") or "@" in match.group():
        return True
    local = match.group("local")
    if re.fullmatch(r"(?:\w )+\w", local) or re.search(r"[\d._-]", local):
        return True
    if _SPOKEN_SEPARATOR.search(local):
        return True
    provider = re.split(r"[\s.]+", match.group("domain").strip())[0].casefold()
    return provider in _MAIL_PROVIDERS or "EMAIL" in hints


def _pairable(run: Run) -> bool:
    """Word runs read as one identifier: digits and pairs, at most one year-like group."""
    return run.years <= 1


def _is_amount(text: str, start: int, end: int) -> bool:
    """A price or quantity: a unit right after it, or a currency word right before."""
    after = _WORD.match(text, len(text) - len(text[end:].lstrip()))
    if after is not None and (after.group() == "%" or fold(after.group()) in UNIT_WORDS):
        return True
    before = text[:start].rstrip()
    if before.endswith("\u20b9"):
        return True
    words = _WORD.findall(before[-12:])
    return bool(words) and fold(words[-1]) in CURRENCY_WORDS and before.endswith(words[-1])


def _grouped_phones(norm: Normalised, hints: set[str], word_spans: list[tuple[int, int]]):
    """Mobile numbers typed in groups: usual groupings always, any other with a phone hint."""
    for match in _GROUPED_RUN.finditer(norm.text):
        if any(match.start() < we and ws < match.end() for ws, we in word_spans):
            continue
        groups = [(m.start() + match.start(), m.group()) for m in re.finditer(r"\d+", match.group())]
        for i in range(len(groups)):
            found = False
            for j in range(len(groups), i, -1):
                window = groups[i:j]
                digits = "".join(group for _, group in window)
                if len(digits) > 12 or not _PHONE_DIGITS.fullmatch(digits):
                    continue
                lengths = tuple(len(group) for _, group in window)
                if len(digits) > 10 and window[0][1] in ("91", "0"):
                    lengths = lengths[1:]
                if lengths in _PHONE_GROUPINGS or "PHONE" in hints:
                    yield window[0][0], window[-1][0] + len(window[-1][1])
                    found = True
                    break
            if found:
                break


def _typed_runs(norm: Normalised) -> list[tuple[int, int, str]]:
    """Digit runs written as digits, in rewritten-text coordinates."""
    word_spans = [(run.norm_start, run.norm_end) for run in norm.runs]
    found = []
    for match in _TYPED_RUN.finditer(norm.text):
        start, end = match.span()
        if any(start < we and ws < end for ws, we in word_spans):
            continue
        found.append((start, end, re.sub(r"\D", "", match.group())))
    return found


def _find(text: str, wanted: Sequence[str], *, mode: Mode, hints: set[str]) -> _Found:
    translated = text.translate(_DIGIT_MAP)  # one-to-one, so offsets stay valid
    norm = normalise(translated)
    spans: list[_Span] = []
    protected = (
        [m.span() for m in _PROTECTED_TOKEN.finditer(translated)] if mode == "log" else []
    )
    strict = mode in ("live", "log")

    def take(start: int, end: int, entity: str, digits: str) -> None:
        if start >= end:
            return
        if any(start < span.end and span.start < end for span in spans):
            return
        # IDs protect only against digit-based matches; an email or PAN still goes.
        if entity not in ("EMAIL", "PAN") and any(
            start < p_end and p_start < end for p_start, p_end in protected
        ):
            return
        spans.append(_Span(start, end, entity, digits))

    def take_norm(norm_start: int, norm_end: int, entity: str) -> None:
        start, end = norm.span(norm_start, norm_end)
        take(start, end, entity, re.sub(r"\D", "", norm.text[norm_start:norm_end]))

    typed_runs = _typed_runs(norm)
    word_spans = [(run.norm_start, run.norm_end) for run in norm.runs]

    for entity in ENTITIES:
        if entity not in wanted:
            continue
        for pattern in _PATTERNS[entity]:
            for match in pattern.finditer(norm.text):
                digits = re.sub(r"\D", "", match.group())
                if entity == "CARD" and not _luhn_ok(digits):
                    continue
                if entity == "AADHAAR" and not _verhoeff_ok(digits):
                    continue
                if pattern is _EMAIL_WORDS and not _email_words_ok(match, hints):
                    continue
                if entity == "NUMBER" and _is_amount(norm.text, *match.span()):
                    continue
                group = "pii" if "pii" in pattern.groupindex else 0
                take_norm(*match.span(group), entity)

        if entity == "PHONE":
            for norm_start, norm_end in _grouped_phones(norm, hints, word_spans):
                take_norm(norm_start, norm_end, entity)

        # Spoken numbers read in pairs ("ninety eight seventy six ...").
        for run in norm.runs:
            digits = run.digits
            if entity in ("PHONE", "AADHAAR", "CARD") and _pairable(run):
                if _identifier(digits, (entity,)) == entity:
                    take(run.start, run.end, entity, digits)
            elif entity == "NUMBER" and _pairable(run) and len(digits) >= 9:
                take(run.start, run.end, entity, digits)

        # The agent asked for an OTP and this is the reply.
        if entity == "OTP" and "OTP" in hints:
            for norm_start, norm_end, digits in typed_runs:
                if 4 <= len(digits) <= 8:
                    take_norm(norm_start, norm_end, entity)
            for run in norm.runs:
                if 4 <= len(run.digits) <= 8:
                    take(run.start, run.end, entity, run.digits)

        # Read out one digit at a time; pairs and years ("twenty twenty five") are not.
        if entity == "NUMBER" and strict:
            for match in _STRICT_NUMBER.finditer(norm.text):
                if not _is_amount(norm.text, *match.span()):
                    take_norm(*match.span(), entity)
            for run in norm.runs:
                if run.digit_by_digit and len(run.digits) >= 4:
                    take(run.start, run.end, entity, run.digits)

    runs = [_DigitRun(run.start, run.end, run.digits, True) for run in norm.runs]
    # With a phone hint, "76 54 32 10" is one part of a number, not four.
    grouped = []
    if "PHONE" in hints:
        grouped = [
            m.span() for m in _GROUPED_RUN.finditer(norm.text)
            if not any(m.start() < we and ws < m.end() for ws, we in word_spans)
        ]
    for norm_start, norm_end in grouped:
        start, end = norm.span(norm_start, norm_end)
        runs.append(_DigitRun(start, end, re.sub(r"\D", "", norm.text[norm_start:norm_end]), True))
    for norm_start, norm_end, digits in typed_runs:
        if any(gs <= norm_start and norm_end <= ge for gs, ge in grouped):
            continue
        start, end = norm.span(norm_start, norm_end)
        runs.append(_DigitRun(start, end, digits, len(digits) < norm_end - norm_start))
    runs.sort(key=lambda run: run.start)
    spans.sort(key=lambda span: span.start)
    return _Found(spans, runs)


def _apply(text: str, spans: Iterable[_Span]) -> str:
    for span in sorted(spans, key=lambda s: s.start, reverse=True):
        text = f"{text[:span.start]}{PLACEHOLDER}{text[span.end:]}"
    return text


def _wanted(entities: Sequence[str] | None) -> tuple[str, ...]:
    return ENTITIES if entities is None else tuple(entities)


# --------------------------------------------------------------------------- #
# Single texts
# --------------------------------------------------------------------------- #


def redact_text(text: str, entities: Sequence[str] | None = None, *, mode: Mode = "stored") -> str:
    """Return ``text`` with every detected entity replaced by ``PLACEHOLDER``."""
    if not text:
        return text
    found = _find(text, _wanted(entities), mode=mode, hints=_hints(text))
    return _apply(text, found.spans)


def redact_if_enabled(text: str) -> str:
    """Redact ``text`` when ``PII_REDACTION_ENABLED`` is set; otherwise return it unchanged."""
    if not is_enabled():
        return text
    return redact_text(text, enabled_entities())


def redact_live_if_enabled(text: str) -> str:
    """Like ``redact_if_enabled``, but also masks partial numbers (logs, live panel)."""
    if not is_enabled():
        return text
    return redact_text(text, enabled_entities(), mode="live")


def redact_progress_if_enabled(text: str, spoken: str, unspoken: str) -> tuple[str, str, str]:
    """Redact a sentence the bot is speaking and its spoken / not-yet-spoken parts.

    The browser panel shows ``spoken`` as a prefix of ``text``; both halves are
    cut from the redacted sentence, so a number half spoken never shows its digits.
    """
    if not is_enabled():
        return text, spoken, unspoken
    wanted = enabled_entities()
    if not text or not spoken or not text.startswith(spoken):
        return (
            redact_text(text, wanted, mode="live"),
            redact_text(spoken, wanted, mode="live"),
            redact_text(unspoken, wanted, mode="live"),
        )
    found = _find(text, wanted, mode="live", hints=_hints(text))
    cut = len(spoken)
    head: list[_Span] = []
    tail_start = cut
    for span in found.spans:
        if span.start < cut:
            head.append(_Span(span.start, min(span.end, cut), span.entity))
            tail_start = max(tail_start, span.end)
    tail_spans = [
        _Span(span.start - tail_start, span.end - tail_start, span.entity)
        for span in found.spans
        if span.start >= tail_start
    ]
    rest = text[tail_start:]
    redacted_rest = _apply(rest, tail_spans)
    if unspoken == text[cut:]:
        redacted_unspoken = redacted_rest
    elif unspoken.strip() == text[cut:].strip():
        redacted_unspoken = redacted_rest.strip()
    else:
        redacted_unspoken = redact_text(unspoken, wanted, mode="live")
    return _apply(text, found.spans), _apply(spoken, head), redacted_unspoken


# --------------------------------------------------------------------------- #
# Whole calls
# --------------------------------------------------------------------------- #


@dataclass
class _Turn:
    role: str
    text: str
    found: _Found


_UPGRADABLE = ("NUMBER", "OTP")


def _overlapping(turn: _Turn, run: _DigitRun) -> list[_Span]:
    return [span for span in turn.found.spans if run.start < span.end and span.start < run.end]


def _open(turn: _Turn, run: _DigitRun) -> bool:
    """Not yet redacted, or redacted only by a weaker rule that may be upgraded."""
    return all(span.entity in _UPGRADABLE for span in _overlapping(turn, run))


def _replace(turn: _Turn, run: _DigitRun, entity: str, digits: str = "") -> None:
    """Redact ``run`` as ``entity``, absorbing any NUMBER/OTP span it overlaps.

    ``digits`` is the whole identifier the run belongs to, when it is a part.
    """
    absorbed = _overlapping(turn, run)
    start = min([run.start] + [span.start for span in absorbed])
    end = max([run.end] + [span.end for span in absorbed])
    kept = [span for span in turn.found.spans if span not in absorbed]
    kept.append(_Span(start, end, entity, digits or run.digits))
    turn.found.spans = sorted(kept, key=lambda span: span.start)


def _known_identifiers(turns: Sequence[_Turn]) -> list[tuple[str, str]]:
    known = []
    for turn in turns:
        for span in turn.found.spans:
            if span.entity in _IDENTIFIERS and len(span.digits) >= 9:
                digits = span.digits[-10:] if span.entity == "PHONE" else span.digits
                known.append((digits, span.entity))
    return known


def _next_same_role(turns: Sequence[_Turn], index: int) -> int | None:
    """Index of the next turn by the same speaker, with at most one turn between."""
    role = turns[index].role
    for offset in (1, 2):
        nxt = index + offset
        if nxt < len(turns) and turns[nxt].role == role:
            return nxt
    return None


def _join_split_numbers(turns: list[_Turn], wanted: Sequence[str]) -> None:
    """A number split over consecutive turns by the same speaker ("97 40" / "80 88 21")."""
    for index, turn in enumerate(turns):
        if not turn.found.runs:
            continue
        head = turn.found.runs[-1]
        if len(head.digits) < 2 or not _open(turn, head):
            continue
        parts = [(turn, head)]
        digits = head.digits
        current = index
        while len(digits) < 19:
            nxt = _next_same_role(turns, current)
            if nxt is None or not turns[nxt].found.runs:
                break
            piece = turns[nxt].found.runs[0]
            if len(piece.digits) < 2 or not _open(turns[nxt], piece):
                break
            parts.append((turns[nxt], piece))
            digits += piece.digits
            entity = _identifier(digits, wanted)
            if entity:
                for part_turn, part_run in parts:
                    _replace(part_turn, part_run, entity, digits)
                break
            # Only a turn that is nothing but this one number can sit in the middle.
            if len(turns[nxt].found.runs) != 1:
                break
            current = nxt


def _redact_fragments_of_known(turns: list[_Turn], wanted: Sequence[str]) -> None:
    """Part of a number given in full elsewhere in the call (the last 8 digits, ...).

    Five or more digits read out one at a time or as words, or seven or more
    written together: a price such as "12000" inside the caller's number
    9820012000 stays.
    """
    known = [(digits, entity) for digits, entity in _known_identifiers(turns) if entity in wanted]
    if not known:
        return
    for turn in turns:
        for run in turn.found.runs:
            long_enough = len(run.digits) >= (5 if run.read_out else 7)
            if not long_enough or not _open(turn, run):
                continue
            for digits, entity in known:
                if run.digits in digits:
                    _replace(turn, run, entity, digits)
                    break


def _analyse_turns(turns: Sequence[tuple[str, str]], wanted: Sequence[str]) -> list[_Turn]:
    all_hints: list[set[str]] = []
    for index, (role, text) in enumerate(turns):
        previous = turns[index - 1] if index else None
        context = previous[1] if previous is not None and previous[0] != role else ""
        all_hints.append(_hints(text, context))
    analysed: list[_Turn] = []
    for index, (role, text) in enumerate(turns):
        hints = set(all_hints[index])
        # "my number is 98" / "76 54 32 10": the hint carries to the rest of the number.
        for back in (1, 2):
            if index >= back and turns[index - back][0] == role and "PHONE" in all_hints[index - back]:
                hints.add("PHONE")
        analysed.append(_Turn(role, text, _find(text or "", wanted, mode="stored", hints=hints)))
    _join_split_numbers(analysed, wanted)
    _redact_fragments_of_known(analysed, wanted)
    return analysed


def redact_turns(turns: Sequence[tuple[str, str]], entities: Sequence[str] | None = None) -> list[str]:
    """Redact every turn of one call, using the rest of the call as context.

    ``turns`` is ``(role, text)`` in call order. Returns the redacted texts.
    """
    return [text for text, _ in redact_turns_with_spans(turns, entities)]


def redact_turns_with_spans(
    turns: Sequence[tuple[str, str]], entities: Sequence[str] | None = None
) -> list[tuple[str, list[tuple[int, int]]]]:
    """Like ``redact_turns``, plus where in each original text the redactions are.

    Each turn gives ``(redacted_text, [(start, end), ...])``; the spans index the
    original text. The call recording uses them to mute the same parts of the audio.
    """
    analysed = _analyse_turns(turns, _wanted(entities))
    return [
        (
            _apply(turn.text, turn.found.spans) if turn.text else turn.text,
            [(span.start, span.end) for span in turn.found.spans],
        )
        for turn in analysed
    ]


def redact_turns_if_enabled(turns: Sequence[tuple[str, str]]) -> list[str]:
    if not is_enabled():
        return [text for _, text in turns]
    return redact_turns(turns, enabled_entities())


def find_spans(text: str, entities: Sequence[str] | None = None, *, mode: Mode = "stored") -> list[tuple[int, int]]:
    """Where in ``text`` something would be redacted, as ``(start, end)`` offsets."""
    if not text:
        return []
    found = _find(text, _wanted(entities), mode=mode, hints=_hints(text))
    return [(span.start, span.end) for span in found.spans]


# --------------------------------------------------------------------------- #
# Logs
# --------------------------------------------------------------------------- #


def log_patcher(record: dict[str, Any]) -> None:
    """Loguru patcher: redact every log message when redaction is enabled.

    Installed for the whole runtime process, so it also covers Pipecat's own lines
    (``Generating TTS [...]`` at DEBUG) and every STT adapter.
    """
    if not is_enabled():
        return
    message = record.get("message")
    exception = record.get("exception")
    if not message and not exception:
        return
    try:
        if message:
            record["message"] = redact_text(message, enabled_entities(), mode="log")
        if exception:
            # A traceback repeats the failing value ("invalid number 9876543210"), and
            # loguru's own formatting adds local variables. Log it redacted, without
            # locals, as part of the message instead.
            kind, value, trace = exception
            formatted = "".join(traceback.format_exception(kind, value, trace)).rstrip()
            redacted = redact_text(formatted, enabled_entities(), mode="log")
            record["message"] = f"{record['message']}\n{redacted}" if record["message"] else redacted
            record["exception"] = None
    except Exception:  # noqa: BLE001 - never let redaction break logging
        record["message"] = "[REDACTION_FAILED]"
        record["exception"] = None
