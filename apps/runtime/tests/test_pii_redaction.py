"""Tests for transcript PII redaction."""

from __future__ import annotations

import pytest

from apps.runtime.services.pipecat.events.logging import register_turn_logging_handlers
from apps.runtime.services.privacy.redaction import redact_if_enabled, redact_text
from apps.runtime.services.storage.transcript import TranscriptWriter


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("mail me at ravi.kumar@example.co.in please", "mail me at [REDACTED_EMAIL] please"),
        ("my number is 9876543210.", "my number is [REDACTED_PHONE]."),
        ("call +91 98765 43210 now", "call [REDACTED_PHONE] now"),
        ("it is 9 8 7 6 5 4 3 2 1 0", "it is [REDACTED_PHONE]"),
        ("aadhaar 2345 6789 0124 hai", "aadhaar [REDACTED_AADHAAR] hai"),
        ("aadhaar 2345-6789-0124", "aadhaar [REDACTED_AADHAAR]"),
        ("aadhaar 234567890124", "aadhaar [REDACTED_AADHAAR]"),
        ("aadhaar 4 9 8 7 6 5 4 3 2 1 0 2", "aadhaar [REDACTED_AADHAAR]"),
        ("call 98765 43210", "call [REDACTED_PHONE]"),
        ("call 09876543210", "call [REDACTED_PHONE]"),
        ("card 3782 822463 10005 amex", "card [REDACTED_CARD] amex"),
        ("PAN is ABCDE1234F", "PAN is [REDACTED_PAN]"),
        ("card 4111 1111 1111 1111 expires soon", "card [REDACTED_CARD] expires soon"),
        ("born on 19/06/1986 in Pune", "born on [REDACTED_DOB] in Pune"),
        ("account 123456789012345 at the bank", "account [REDACTED_NUMBER] at the bank"),
    ],
)
def test_redacts_each_entity(text: str, expected: str) -> None:
    assert redact_text(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "I have 3 acres and need 50 kg of seed",
        "the amount is 250000 rupees",
        "pin code 411001",
        "",
    ],
)
def test_leaves_ordinary_text_alone(text: str) -> None:
    assert redact_text(text) == text


# Separately spoken numbers must not merge into one identifier: redaction is
# irreversible, and on a price-information agent these numbers are the call.
@pytest.mark.parametrize(
    "text",
    [
        "आज का भाव 2400 2500 2600 रुपये है",
        "soybean 4200 4300 4400 4500",
        "rate 1800 1900 2000 tha",
        "500 600 700 quintal becha",
        "pichhle hafte 98 99 100 101 102 tha",
        "mandi mein 6200 6300 aur 6400",
    ],
)
def test_separate_numbers_are_not_merged(text: str) -> None:
    assert redact_text(text) == text


def test_aadhaar_grouping_needs_valid_checksum() -> None:
    # Right shape, wrong Verhoeff check digit: left alone when spaced ...
    assert redact_text("2345 6789 0123") == "2345 6789 0123"
    # ... and caught by the long-number catch-all when written together.
    assert redact_text("234567890123") == "[REDACTED_NUMBER]"


def test_mixed_separators_are_not_one_identifier() -> None:
    assert redact_text("2345-6789 0124") == "2345-6789 0124"


def test_redacts_arabic_indic_digits() -> None:
    urdu = "".join(chr(0x06F0 + int(digit)) for digit in "9876543210")
    arabic = "".join(chr(0x0660 + int(digit)) for digit in "9876543210")
    assert redact_text(f"نمبر {urdu}") == "نمبر [REDACTED_PHONE]"
    assert redact_text(f"رقم {arabic}") == "رقم [REDACTED_PHONE]"


def test_redacts_devanagari_digits() -> None:
    number = "".join(chr(0x0966 + int(digit)) for digit in "9876543210")
    assert redact_text(f"number {number} ok") == "number [REDACTED_PHONE] ok"


def test_redacts_several_entities_in_one_line() -> None:
    text = "reach me on 9876543210 or a.b@example.com"
    assert redact_text(text) == "reach me on [REDACTED_PHONE] or [REDACTED_EMAIL]"


def test_entity_subset_is_respected() -> None:
    text = "9876543210 and a.b@example.com"
    assert redact_text(text, ("EMAIL",)) == "9876543210 and [REDACTED_EMAIL]"


def test_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PII_REDACTION_ENABLED", raising=False)
    assert redact_if_enabled("my number is 9876543210") == "my number is 9876543210"


def test_enabled_by_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_REDACTION_ENABLED", "true")
    monkeypatch.delenv("PII_REDACTION_ENTITIES", raising=False)
    assert redact_if_enabled("my number is 9876543210") == "my number is [REDACTED_PHONE]"


def test_entities_env_limits_what_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_REDACTION_ENABLED", "true")
    monkeypatch.setenv("PII_REDACTION_ENTITIES", "email, pan")
    text = "9876543210 a.b@example.com ABCDE1234F"
    assert redact_if_enabled(text) == "9876543210 [REDACTED_EMAIL] [REDACTED_PAN]"


def test_transcript_writer_redacts_content(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_REDACTION_ENABLED", "true")
    monkeypatch.delenv("PII_REDACTION_ENTITIES", raising=False)
    writer = TranscriptWriter(org_id="org-1", call_id="call-1")
    writer.append("user", "2026-11-16T10:00:00+00:00", "my number is 9876543210")
    assert "9876543210" not in writer._buffer
    assert "[2026-11-16T10:00:00+00:00] user: my number is [REDACTED_PHONE]" in writer._buffer


class _FakeAggregator:
    """Captures the handler registered through ``event_handler``."""

    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}

    def event_handler(self, name: str):
        def register(fn):
            self.handlers[name] = fn
            return fn

        return register


@pytest.mark.asyncio
async def test_turn_logs_are_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from loguru import logger

    monkeypatch.setenv("PII_REDACTION_ENABLED", "true")
    monkeypatch.delenv("PII_REDACTION_ENTITIES", raising=False)
    user, assistant = _FakeAggregator(), _FakeAggregator()
    register_turn_logging_handlers(user, assistant, session_label="test")

    lines: list[str] = []
    sink = logger.add(lambda message: lines.append(str(message)), level="INFO")
    try:
        message = SimpleNamespace(timestamp="t0", content="call me on 9876543210")
        await user.handlers["on_user_turn_stopped"](None, None, message)
        reply = SimpleNamespace(timestamp="t1", content="noted 9876543210", interrupted=False)
        await assistant.handlers["on_assistant_turn_stopped"](None, reply)
    finally:
        logger.remove(sink)

    joined = "".join(lines)
    assert "9876543210" not in joined
    assert joined.count("[REDACTED_PHONE]") == 2
