"""Tests for transcript PII redaction (VE-122, VE-221)."""

from __future__ import annotations

import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from apps.runtime.services.pipecat.events.logging import register_turn_logging_handlers
from apps.runtime.services.privacy.number_words import normalise
from apps.runtime.services.privacy.redaction import (
    log_patcher,
    redact_if_enabled,
    redact_progress_if_enabled,
    redact_text,
    redact_turns,
)
from apps.runtime.services.privacy.rtvi import (
    RedactingRTVIProcessor,
    redact_rtvi_message,
)
from apps.runtime.services.storage import transcript as transcript_module
from apps.runtime.services.storage.transcript import TranscriptWriter


@pytest.fixture
def enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_REDACTION_ENABLED", "true")
    monkeypatch.delenv("PII_REDACTION_ENTITIES", raising=False)


def _digits(chars: str, zero: int) -> str:
    return "".join(chr(zero + int(char)) if char.isdigit() else char for char in chars)


# --------------------------------------------------------------------------- #
# Digits (VE-122)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("mail me at ravi.kumar@example.co.in please", "mail me at [REDACTED_TEXT] please"),
        ("my number is 9876543210.", "my number is [REDACTED_TEXT]."),
        ("call +91 98765 43210 now", "call [REDACTED_TEXT] now"),
        ("it is 9 8 7 6 5 4 3 2 1 0", "it is [REDACTED_TEXT]"),
        ("aadhaar 2345 6789 0124 hai", "aadhaar [REDACTED_TEXT] hai"),
        ("aadhaar 2345-6789-0124", "aadhaar [REDACTED_TEXT]"),
        ("aadhaar 234567890124", "aadhaar [REDACTED_TEXT]"),
        ("aadhaar 4 9 8 7 6 5 4 3 2 1 0 2", "aadhaar [REDACTED_TEXT]"),
        ("call 98765 43210", "call [REDACTED_TEXT]"),
        ("call 09876543210", "call [REDACTED_TEXT]"),
        ("card 3782 822463 10005 amex", "card [REDACTED_TEXT] amex"),
        ("PAN is ABCDE1234F", "PAN is [REDACTED_TEXT]"),
        ("card 4111 1111 1111 1111 expires soon", "card [REDACTED_TEXT] expires soon"),
        ("born on 19/06/1986 in Pune", "born on [REDACTED_TEXT] in Pune"),
        ("account 123456789012345 at the bank", "account [REDACTED_TEXT] at the bank"),
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
    assert redact_text("234567890123") == "[REDACTED_TEXT]"


def test_mixed_separators_are_not_one_identifier() -> None:
    assert redact_text("2345-6789 0124") == "2345-6789 0124"


def test_redacts_arabic_indic_digits() -> None:
    urdu = "".join(chr(0x06F0 + int(digit)) for digit in "9876543210")
    arabic = "".join(chr(0x0660 + int(digit)) for digit in "9876543210")
    assert redact_text(f"نمبر {urdu}") == "نمبر [REDACTED_TEXT]"
    assert redact_text(f"رقم {arabic}") == "رقم [REDACTED_TEXT]"


def test_redacts_devanagari_digits() -> None:
    number = "".join(chr(0x0966 + int(digit)) for digit in "9876543210")
    assert redact_text(f"number {number} ok") == "number [REDACTED_TEXT] ok"


def test_redacts_full_kannada_numeral_phone() -> None:
    # VE-221 "not fully tested": a full 10-digit number in Kannada numerals.
    assert redact_text(_digits("9 8 7 6 5 4 3 2 1 0", 0x0CE6)) == "[REDACTED_TEXT]"
    assert redact_text(_digits("9876543210", 0x0CE6)) == "[REDACTED_TEXT]"


def test_redacts_several_entities_in_one_line() -> None:
    text = "reach me on 9876543210 or a.b@example.com"
    assert redact_text(text) == "reach me on [REDACTED_TEXT] or [REDACTED_TEXT]"


def test_entity_subset_is_respected() -> None:
    text = "9876543210 and a.b@example.com"
    assert redact_text(text, ("EMAIL",)) == "9876543210 and [REDACTED_TEXT]"


# --------------------------------------------------------------------------- #
# VE-221 AC1: numbers the caller speaks, written as words by speech recognition
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # English, one digit at a time
        ("my mobile number is nine eight seven six five four three two one zero",
         "my mobile number is [REDACTED_TEXT]"),
        ("nine, eight, seven, six, five, four, three, two, one, zero", "[REDACTED_TEXT]"),
        ("double nine eight seven six five four three two one", "[REDACTED_TEXT]"),
        ("nine oh eight seven six five four three two one", "[REDACTED_TEXT]"),
        # English, in pairs
        ("ninety eight seventy six fifty four thirty two ten", "[REDACTED_TEXT]"),
        # Hindi
        ("मेरा नंबर नौ आठ सात छह पाँच चार तीन दो एक शून्य है", "मेरा नंबर [REDACTED_TEXT] है"),
        ("अट्ठानवे छिहत्तर चौवन बत्तीस दस", "[REDACTED_TEXT]"),
        # Kannada
        ("ನನ್ನ ನಂಬರ್ ಒಂಬತ್ತು ಎಂಟು ಏಳು ಆರು ಐದು ನಾಲ್ಕು ಮೂರು ಎರಡು ಒಂದು ಸೊನ್ನೆ",
         "ನನ್ನ ನಂಬರ್ [REDACTED_TEXT]"),
        ("ತೊಂಬತ್ತೆಂಟು ಎಪ್ಪತ್ತಾರು ಐವತ್ತನಾಲ್ಕು ಮೂವತ್ತೆರಡು ಹತ್ತು", "[REDACTED_TEXT]"),
        # Marathi
        ("नऊ आठ सात सहा पाच चार तीन दोन एक शून्य", "[REDACTED_TEXT]"),
        # PAN spelled out letter by letter ("a b c d e one two three four f")
        ("my PAN is a b c d e one two three four f", "my PAN is [REDACTED_TEXT]"),
        ("PAN ABCDE 1234 F", "PAN [REDACTED_TEXT]"),
        # Aadhaar and card read out as words (checksums still apply)
        ("two three four five six seven eight nine zero one two four", "[REDACTED_TEXT]"),
        ("four one one one one one one one one one one one one one one one", "[REDACTED_TEXT]"),
        # OTP
        ("my OTP is four five six seven", "my OTP is [REDACTED_TEXT]"),
        ("OTP 4 5 6 7 8 9", "OTP [REDACTED_TEXT]"),
        ("ओटीपी है 482910", "ओटीपी है [REDACTED_TEXT]"),
        # A landline or account number read out one digit at a time (7+ digits)
        ("two two five six seven eight nine one", "[REDACTED_TEXT]"),
    ],
)
def test_redacts_spoken_numbers(text: str, expected: str) -> None:
    assert redact_text(text) == expected


@pytest.mark.parametrize(
    ("text", "entity"),
    [
        ("my mobile number is nine eight seven six five four three two one zero", "PHONE"),
        ("ತೊಂಬತ್ತೆಂಟು ಎಪ್ಪತ್ತಾರು ಐವತ್ತನಾಲ್ಕು ಮೂವತ್ತೆರಡು ಹತ್ತು", "PHONE"),
        ("my PAN is a b c d e one two three four f", "PAN"),
        ("two three four five six seven eight nine zero one two four", "AADHAAR"),
        ("four one one one one one one one one one one one one one one one", "CARD"),
        ("my OTP is four five six seven", "OTP"),
        ("asha dot rao at example dot com", "EMAIL"),
        ("fifteen december twenty twenty one", "DOB"),
        ("two two five six seven eight nine one", "NUMBER"),
    ],
)
def test_spoken_forms_are_detected_as_the_right_type(text: str, entity: str) -> None:
    # Output never names the type, so check it by enabling only that type.
    assert "[REDACTED_TEXT]" in redact_text(text, (entity,))


def test_no_type_name_is_ever_written(enabled: None) -> None:
    text = (
        "phone 9876543210, aadhaar 2345 6789 0124, PAN ABCDE1234F, card 4111 1111 1111 1111, "
        "email a.b@example.com, DOB 15 December 2021, OTP 4567, account 123456789012345"
    )
    outputs = [
        redact_text(text),
        redact_text(text, mode="live"),
        redact_text(text, mode="log"),
        *redact_turns([("user", text)]),
    ]
    record = {"message": text}
    log_patcher(record)
    outputs.append(record["message"])
    message = redact_rtvi_message({"type": "user-transcription", "data": {"text": text}})
    outputs.append(message["data"]["text"])
    expected = (
        "phone [REDACTED_TEXT], aadhaar [REDACTED_TEXT], PAN [REDACTED_TEXT], "
        "card [REDACTED_TEXT], email [REDACTED_TEXT], DOB [REDACTED_TEXT], "
        "OTP [REDACTED_TEXT], account [REDACTED_TEXT]"
    )
    for output in outputs:
        assert output == expected
        assert re.findall(r"REDACTED_\w+", output) == ["REDACTED_TEXT"] * 8


@pytest.mark.parametrize(
    "text",
    [
        "the rate is twenty four hundred, twenty five hundred",
        "I need one or two bags",
        "I do it every day",
        "I am twenty five years old",
        "it costs five thousand rupees",
        "दो तीन दिन में आ जाएगा",
        "चौबीस सौ पच्चीस सौ",
        "twenty twenty one, twenty twenty two, twenty twenty three",
        "oh no, one second",
        "five six zero zero zero one",  # a pin code read out: six digits stay
    ],
)
def test_spoken_numbers_that_are_not_pii_stay(text: str) -> None:
    assert redact_text(text) == text


def test_normalise_maps_back_to_the_original_words() -> None:
    norm = normalise("call nine eight seven now")
    assert norm.text == "call 9 8 7 now"
    start, end = norm.span(norm.text.index("9"), norm.text.index("7") + 1)
    assert "call nine eight seven now"[start:end] == "nine eight seven"


@pytest.mark.parametrize(
    ("words", "digits"),
    [
        ("twenty twenty one", "2021"),
        ("nineteen eighty six", "1986"),
        ("two thousand and five", "2005"),
        ("twenty oh five", "2005"),
        ("दो हज़ार इक्कीस", "2021"),
        ("ಎರಡು ಸಾವಿರದ ಇಪ್ಪತ್ತೊಂದು", "2021"),
        ("ಇಪ್ಪತ್ಮೂರು", "23"),
        ("पाँच", "5"),
        ("पांच", "5"),
    ],
)
def test_number_words(words: str, digits: str) -> None:
    assert normalise(words).runs[0].digits == digits


# --------------------------------------------------------------------------- #
# VE-221 AC2: email written as words
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("asha dot rao at example dot com", "[REDACTED_TEXT]"),
        ("Your email is asha.rao@example.com, that is asha dot rao at example dot com.",
         "Your email is [REDACTED_TEXT], that is [REDACTED_TEXT]."),
        ("ravi at gmail dot com", "[REDACTED_TEXT]"),
        ("ravi123 at the rate yahoo dot co dot in", "[REDACTED_TEXT]"),
        ("r a v i at gmail dot com", "[REDACTED_TEXT]"),
        ("my email is kislaya at coss dot org dot in", "my email is [REDACTED_TEXT]"),
        ("asha.rao at example.com", "[REDACTED_TEXT]"),
    ],
)
def test_redacts_spoken_email(text: str, expected: str) -> None:
    assert redact_text(text) == expected


@pytest.mark.parametrize(
    "text",
    ["look at google dot com", "meet me at the office", "kislaya at coss dot org dot in"],
)
def test_spoken_web_addresses_are_not_emails(text: str) -> None:
    # Without "email" nearby, "name at domain dot org" could be a website.
    assert redact_text(text) == text


# --------------------------------------------------------------------------- #
# VE-221 AC3: dates of birth with month names
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Your date of birth is 15 December 2021.", "Your date of birth is [REDACTED_TEXT]."),
        ("15-12-2021 ... 15 December 2021", "[REDACTED_TEXT] ... [REDACTED_TEXT]"),
        ("born 15th of December, 2021", "born [REDACTED_TEXT]"),
        ("December 15, 2021", "[REDACTED_TEXT]"),
        ("15-Dec-2021", "[REDACTED_TEXT]"),
        ("my date of birth is fifteen twelve twenty twenty one", "my date of birth is [REDACTED_TEXT]"),
        ("fifteen december twenty twenty one", "[REDACTED_TEXT]"),
        ("the fifteenth of December, two thousand and five", "the [REDACTED_TEXT]"),
        ("पंद्रह दिसंबर दो हज़ार इक्कीस", "[REDACTED_TEXT]"),
        ("जन्म तिथि 15 दिसंबर 2021", "जन्म तिथि [REDACTED_TEXT]"),
        ("ಹದಿನೈದು ಡಿಸೆಂಬರ್ ಎರಡು ಸಾವಿರದ ಇಪ್ಪತ್ತೊಂದು", "[REDACTED_TEXT]"),
        (_digits("೧೫ ಡಿಸೆಂಬರ್ 2021", 0x0CE6), "[REDACTED_TEXT]"),
    ],
)
def test_redacts_dates_with_month_names(text: str, expected: str) -> None:
    assert redact_text(text) == expected


@pytest.mark.parametrize("text", ["the year 2026", "in December 2021", "15 maybe 2021", "may 15"])
def test_dates_without_a_full_date_stay(text: str) -> None:
    assert redact_text(text) == text


# --------------------------------------------------------------------------- #
# VE-221 AC4: numbers said in parts
# --------------------------------------------------------------------------- #


def test_partial_number_in_kannada_numerals() -> None:
    # The agent repeated only 8 of the 10 digits, in Kannada numerals.
    assert redact_text("೭ ೬ ೫ ೪ ೩ ೨ ೧ ೦") == "[REDACTED_TEXT]"


def test_number_split_over_two_turns() -> None:
    turns = [
        ("assistant", "Please tell me your mobile number."),
        ("user", "nine eight seven six"),
        ("user", "five four three two one zero"),
    ]
    assert redact_turns(turns) == [turns[0][1], "[REDACTED_TEXT]", "[REDACTED_TEXT]"]
    # Recognised as one phone number, not as two loose numbers.
    assert redact_turns(turns, ("PHONE",))[1:] == ["[REDACTED_TEXT]", "[REDACTED_TEXT]"]


def test_number_split_with_the_agent_speaking_in_between() -> None:
    turns = [
        ("user", "ಒಂಬತ್ತು ಎಂಟು ಏಳು ಆರು"),
        ("assistant", "ಹೌದು, ಮುಂದುವರಿಸಿ"),
        ("user", "ಐದು ನಾಲ್ಕು ಮೂರು ಎರಡು ಒಂದು ಸೊನ್ನೆ"),
    ]
    assert redact_turns(turns) == ["[REDACTED_TEXT]", turns[1][1], "[REDACTED_TEXT]"]


def test_repeat_of_part_of_a_split_number() -> None:
    turns = [
        ("user", "ಒಂಬತ್ತು ಎಂಟು"),
        ("user", "ಏಳು ಆರು ಐದು ನಾಲ್ಕು ಮೂರು ಎರಡು ಒಂದು ಸೊನ್ನೆ"),
        ("assistant", "ನಿಮ್ಮ ಸಂಖ್ಯೆ ೭ ೬ ೫ ೪ ೩ ೨ ೧ ೦, ಸರಿಯೇ?"),
        ("assistant", "ಕೊನೆಯ ಅಂಕೆಗಳು ೪ ೩ ೨ ೧ ೦"),
    ]
    # Only PHONE enabled: the partial repeats are known to belong to the phone.
    assert redact_turns(turns, ("PHONE",))[2:] == [
        "ನಿಮ್ಮ ಸಂಖ್ಯೆ [REDACTED_TEXT], ಸರಿಯೇ?",
        "ಕೊನೆಯ ಅಂಕೆಗಳು [REDACTED_TEXT]",
    ]


def test_aadhaar_said_in_three_parts() -> None:
    turns = [("user", "2345"), ("user", "6789"), ("user", "0124")]
    assert redact_turns(turns, ("AADHAAR",)) == ["[REDACTED_TEXT]"] * 3


def test_part_of_a_number_given_in_full_elsewhere_in_the_call() -> None:
    turns = [
        ("user", "my number is 9876543210"),
        ("assistant", "I have noted the number ending 76543210."),
        ("assistant", "So that is 4 3 2 1 0, correct?"),
        ("user", "yes, five four three two one zero"),
    ]
    # Only PHONE enabled: each part is known to belong to the phone given first.
    assert redact_turns(turns, ("PHONE",)) == [
        "my number is [REDACTED_TEXT]",
        "I have noted the number ending [REDACTED_TEXT].",
        "So that is [REDACTED_TEXT], correct?",
        "yes, [REDACTED_TEXT]",
    ]


def test_a_price_inside_a_known_number_stays() -> None:
    turns = [
        ("user", "my number is 9820012000"),
        ("assistant", "The price is 12000 rupees, or 200120 for the season."),
    ]
    assert redact_turns(turns)[1] == turns[1][1]


def test_otp_and_email_given_in_reply_to_the_agent() -> None:
    turns = [
        ("assistant", "Please tell me the OTP you received."),
        ("user", "four five six seven"),
        ("assistant", "What is your email address?"),
        ("user", "kislaya at coss dot org dot in"),
    ]
    assert redact_turns(turns)[1::2] == ["[REDACTED_TEXT]", "[REDACTED_TEXT]"]
    assert redact_turns(turns, ("OTP",))[1] == "[REDACTED_TEXT]"
    assert redact_turns(turns, ("EMAIL",))[3] == "[REDACTED_TEXT]"


def test_call_context_does_not_merge_unrelated_numbers() -> None:
    turns = [
        ("user", "I want 25 bags"),
        ("user", "the rate was 2400 2500 2600"),
        ("assistant", "The price today is 2400 rupees."),
    ]
    assert redact_turns(turns) == [text for _, text in turns]


def test_whole_call_kannada_split_number_and_partial_repeat() -> None:
    turns = [
        ("assistant", "ನಿಮ್ಮ ಮೊಬೈಲ್ ಸಂಖ್ಯೆ ಹೇಳಿ"),
        ("user", "ಒಂಬತ್ತು ಎಂಟು"),
        ("user", "ಏಳು ಆರು ಐದು ನಾಲ್ಕು ಮೂರು ಎರಡು ಒಂದು ಸೊನ್ನೆ"),
        ("assistant", "ನಿಮ್ಮ ಸಂಖ್ಯೆ ೭ ೬ ೫ ೪ ೩ ೨ ೧ ೦, ಸರಿಯೇ?"),
        ("assistant", "ನಿಮ್ಮ ಸಂಖ್ಯೆ 9876543210"),
    ]
    redacted = redact_turns(turns, ("PHONE",))
    assert redacted[1:3] == ["[REDACTED_TEXT]", "[REDACTED_TEXT]"]
    assert redacted[3] == "ನಿಮ್ಮ ಸಂಖ್ಯೆ [REDACTED_TEXT], ಸರಿಯೇ?"
    assert redacted[4] == "ನಿಮ್ಮ ಸಂಖ್ಯೆ [REDACTED_TEXT]"


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #


def test_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PII_REDACTION_ENABLED", raising=False)
    assert redact_if_enabled("my number is 9876543210") == "my number is 9876543210"


def test_enabled_by_env(enabled: None) -> None:
    assert redact_if_enabled("my number is 9876543210") == "my number is [REDACTED_TEXT]"


def test_entities_env_limits_what_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_REDACTION_ENABLED", "true")
    monkeypatch.setenv("PII_REDACTION_ENTITIES", "email, pan")
    text = "9876543210 a.b@example.com ABCDE1234F"
    assert redact_if_enabled(text) == "9876543210 [REDACTED_TEXT] [REDACTED_TEXT]"


# --------------------------------------------------------------------------- #
# Stored transcript
# --------------------------------------------------------------------------- #


def test_transcript_writer_redacts_content(enabled: None) -> None:
    writer = TranscriptWriter(org_id="org-1", call_id="call-1")
    writer.append("user", "2026-11-16T10:00:00+00:00", "my number is 9876543210")
    rendered = writer.render()
    assert "9876543210" not in rendered
    assert "[2026-11-16T10:00:00+00:00] user: my number is [REDACTED_TEXT]" in rendered


def test_transcript_writer_redacts_across_turns(enabled: None) -> None:
    writer = TranscriptWriter(org_id="org-1", call_id="call-1")
    writer.append("user", "t0", "nine eight seven six")
    writer.append("user", "t1", "five four three two one zero")
    rendered = writer.render()
    assert "nine" not in rendered and "eight" not in rendered
    assert rendered.count("[REDACTED_TEXT]") == 2


def test_transcript_writer_keeps_text_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PII_REDACTION_ENABLED", raising=False)
    writer = TranscriptWriter(org_id="org-1", call_id="call-1")
    writer.append("user", "t0", "my number is 9876543210")
    assert "user: my number is 9876543210" in writer.render()


@pytest.mark.asyncio
async def test_transcript_flush_uploads_redacted_text_and_drops_raw(
    enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload = AsyncMock(return_value=True)
    monkeypatch.setattr(transcript_module, "save_and_link", upload)
    writer = TranscriptWriter(org_id="org-1", call_id="call-1")
    writer.append("user", "t0", "nine eight seven six")
    writer.append("user", "t1", "five four three two one zero")
    await writer.flush()
    data = upload.await_args.kwargs["data"].decode("utf-8")
    assert data.count("[REDACTED_TEXT]") == 2
    assert writer._lines == []
    await writer.flush()
    assert upload.await_count == 1


# --------------------------------------------------------------------------- #
# VE-221 AC5: logs and the browser test panel
# --------------------------------------------------------------------------- #


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
async def test_turn_logs_are_redacted(enabled: None) -> None:
    from loguru import logger

    user, assistant = _FakeAggregator(), _FakeAggregator()
    register_turn_logging_handlers(user, assistant, session_label="test")

    lines: list[str] = []
    sink = logger.add(lambda message: lines.append(str(message)), level="INFO")
    try:
        message = SimpleNamespace(timestamp="t0", content="call me on 9876543210")
        await user.handlers["on_user_turn_stopped"](None, None, message)
        partial = SimpleNamespace(timestamp="t1", content="nine eight seven six")
        await user.handlers["on_user_turn_stopped"](None, None, partial)
        reply = SimpleNamespace(timestamp="t2", content="noted 9876543210", interrupted=False)
        await assistant.handlers["on_assistant_turn_stopped"](None, reply)
    finally:
        logger.remove(sink)

    joined = "".join(lines)
    assert "9876543210" not in joined and "nine seven" not in joined
    assert joined.count("[REDACTED_TEXT]") == 3


def test_log_patcher_redacts_any_log_line(enabled: None) -> None:
    record = {"message": "Generating TTS [Your number is 9876543210 and DOB 15 December 2021]"}
    log_patcher(record)
    assert record["message"] == "Generating TTS [Your number is [REDACTED_TEXT] and DOB [REDACTED_TEXT]]"


def test_log_patcher_keeps_ids_traceable(enabled: None) -> None:
    message = (
        "Linked call_id=3f2b9c1e-7a4d-4e8b-9c21-5d6e7f8a9b0c "
        "uri=minio://voicera-calls/6744a1b2c3d4e5f601234567/x sample_rate=16000"
    )
    record = {"message": message}
    log_patcher(record)
    assert record["message"] == message


def test_log_patcher_still_redacts_emails_and_phones_next_to_ids(enabled: None) -> None:
    record = {"message": "call_id=6744a1b2c3d4e5f601234567 from=+919876543210 user=ravi9876543210@gmail.com"}
    log_patcher(record)
    assert record["message"] == "call_id=6744a1b2c3d4e5f601234567 from=[REDACTED_TEXT] user=[REDACTED_TEXT]"


def test_log_patcher_is_off_when_redaction_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PII_REDACTION_ENABLED", raising=False)
    record = {"message": "user: 9876543210"}
    log_patcher(record)
    assert record["message"] == "user: 9876543210"


def test_rtvi_user_transcription_is_redacted(enabled: None) -> None:
    message = {
        "label": "rtvi-ai",
        "type": "user-transcription",
        "data": {"text": "nine eight seven six", "user_id": "", "timestamp": "t", "final": False},
    }
    assert redact_rtvi_message(message)["data"]["text"] == "[REDACTED_TEXT]"


def test_rtvi_bot_output_progress_is_redacted_consistently(enabled: None) -> None:
    text = "Your date of birth is 15-12-2021, 15 December 2021."
    cut = text.index("December")
    message = {
        "type": "bot-output",
        "data": {
            "text": text,
            "spoken_status": "in-progress",
            "spoken_progress": {"accumulated_text": text[:cut], "remaining_text": text[cut:]},
        },
    }
    data = redact_rtvi_message(message)["data"]
    assert data["text"] == "Your date of birth is [REDACTED_TEXT], [REDACTED_TEXT]."
    spoken = data["spoken_progress"]["accumulated_text"]
    assert spoken == "Your date of birth is [REDACTED_TEXT], [REDACTED_TEXT]"
    assert data["text"].startswith(spoken)
    assert data["spoken_progress"]["remaining_text"] == "."


def test_progress_split_inside_a_number(enabled: None) -> None:
    text = "Your number is 9876543210, right?"
    assert redact_progress_if_enabled(text, "Your number is 98765", "43210, right?") == (
        "Your number is [REDACTED_TEXT], right?",
        "Your number is [REDACTED_TEXT]",
        ", right?",
    )


@pytest.mark.parametrize("kind", ["bot-llm-text", "bot-tts-text", "bot-transcription"])
def test_rtvi_streamed_text_is_not_sent(enabled: None, kind: str) -> None:
    assert redact_rtvi_message({"type": kind, "data": {"text": "9876"}}) is None


def test_rtvi_messages_pass_through_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PII_REDACTION_ENABLED", raising=False)
    message = {"type": "bot-llm-text", "data": {"text": "9876543210"}}
    assert redact_rtvi_message(message) == message


@pytest.mark.asyncio
async def test_redacting_rtvi_processor_pushes_redacted_frames(enabled: None) -> None:
    from pipecat.processors.frameworks.rtvi import models as RTVI

    processor = RedactingRTVIProcessor()
    processor.push_frame = AsyncMock()  # type: ignore[method-assign]
    await processor.push_transport_message(
        RTVI.BotTTSTextMessage(data=RTVI.TextMessageData(text="nine"))
    )
    processor.push_frame.assert_not_awaited()
    await processor.push_transport_message(
        RTVI.UserTranscriptionMessage(
            data=RTVI.UserTranscriptionMessageData(
                text="my number is 9876543210", user_id="", timestamp="t", final=True
            )
        )
    )
    frame = processor.push_frame.await_args.args[0]
    assert frame.message["data"]["text"] == "my number is [REDACTED_TEXT]"
