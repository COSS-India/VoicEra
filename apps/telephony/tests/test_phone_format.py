"""Tests for CallLog phone formatting."""

from __future__ import annotations

from apps.telephony.phone_format import format_e164_for_call_log


def test_format_e164_for_call_log_indian_ten_digit() -> None:
    assert format_e164_for_call_log("9876543210") == "+919876543210"


def test_format_e164_for_call_log_indian_with_country_code() -> None:
    assert format_e164_for_call_log("919876543210") == "+919876543210"
    assert format_e164_for_call_log("+919876543210") == "+919876543210"


def test_format_e164_for_call_log_indian_leading_zero() -> None:
    assert format_e164_for_call_log("09876543210") == "+919876543210"


def test_format_e164_for_call_log_unknown_passthrough() -> None:
    assert format_e164_for_call_log("unknown") == "unknown"
    assert format_e164_for_call_log("") == "unknown"


def test_format_e164_for_call_log_international_passthrough() -> None:
    assert format_e164_for_call_log("+14155552671") == "+14155552671"
