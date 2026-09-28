"""Phone formatting for CallLog storage and display (E.164)."""

from __future__ import annotations

import re

_PHONE_DIGITS = re.compile(r"\D+")
_E164_RE = re.compile(r"^\+[0-9]{7,15}$")


def _digits_only(number: str) -> str:
    return _PHONE_DIGITS.sub("", str(number or "").strip().lstrip("+"))


def _looks_like_indian_mobile(digits: str) -> bool:
    if len(digits) == 10 and digits.isdigit() and digits[0] in "6789":
        return True
    if digits.startswith("91") and len(digits) == 12 and digits.isdigit():
        return True
    if (
        digits.startswith("0")
        and len(digits) == 11
        and digits[1:].isdigit()
        and digits[1] in "6789"
    ):
        return True
    return False


def format_e164_for_call_log(number: str) -> str:
    """Canonicalize phone strings for CallLog / History.

    Indian mobiles (10-digit, ``91…``, ``0…``, ``+91…``) become ``+91XXXXXXXXXX``.
    Other values already in E.164 are kept; unknown placeholders pass through.
    """
    raw = str(number or "").strip()
    if not raw or raw.lower() == "unknown":
        return raw or "unknown"

    cleaned = raw.replace(" ", "").replace("-", "")
    if cleaned.startswith("+") and _E164_RE.match(cleaned):
        return cleaned

    digits = _digits_only(raw)
    if _looks_like_indian_mobile(digits):
        if digits.startswith("0") and len(digits) == 11:
            digits = f"91{digits[1:]}"
        elif len(digits) == 10:
            digits = f"91{digits}"
        if digits.startswith("91") and len(digits) == 12:
            return f"+{digits}"

    if digits.isdigit() and len(digits) >= 7:
        return f"+{digits}"

    return raw
