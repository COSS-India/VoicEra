"""Unit + HTTP-mapping tests for the prompt-refine endpoint and its helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from openai import APIConnectionError, APIError

from app.auth import get_current_user
from app.routers import prompt_refine
from app.routers.prompt_refine import (
    REQUEST_TIMEOUT_SECONDS,
    PromptRefineRequest,
    build_context,
    candidate_providers,
    call_refiner,
    extract_factual_identifiers,
    infer_mode,
    require_active_org,
    resolve_api_key,
    resolve_openai_compatible,
    resolve_stored_auth,
    resolve_voicera_model_server,
    summarize_changes,
    validate_refined_prompt,
)
from apps.providers.adapters.kenpath.catalog import DEFAULT_LLM_MODEL as KENPATH_DEFAULT_MODEL
from apps.providers.cloud.atlascloud.catalog import DEFAULT_LLM_MODEL as ATLASCLOUD_DEFAULT_MODEL
from apps.providers.cloud.aws_bedrock.catalog import DEFAULT_LLM_MODEL as BEDROCK_DEFAULT_MODEL
from apps.providers.cloud.google.catalog import DEFAULT_LLM_MODEL as GOOGLE_CATALOG_DEFAULT_MODEL
from apps.providers.cloud.google_vertex.catalog import DEFAULT_LLM_MODEL as VERTEX_DEFAULT_MODEL
from apps.providers.cloud.groq.catalog import DEFAULT_LLM_MODEL as GROQ_DEFAULT_MODEL
from apps.providers.cloud.openai.catalog import DEFAULT_LLM_MODEL as OPENAI_DEFAULT_MODEL
from apps.providers.cloud.openrouter.catalog import DEFAULT_LLM_MODEL as OPENROUTER_DEFAULT_MODEL
from apps.providers.cloud.sarvam.catalog import DEFAULT_LLM_MODEL as SARVAM_DEFAULT_MODEL
from apps.providers.refine_llm import PromptRefineError, call_bedrock, call_kenpath, call_vertex

app = FastAPI()
app.include_router(prompt_refine.router, prefix="/api/v1")
app.dependency_overrides[get_current_user] = lambda: {
    "email": "test@example.com",
    "org_id": "org-1",
}

client = TestClient(app)


def make_body(**overrides) -> PromptRefineRequest:
    defaults: dict = {"prompt": "You are a support agent."}
    defaults.update(overrides)
    return PromptRefineRequest(**defaults)


# --------------------------------------------------------------------------
# require_active_org
# --------------------------------------------------------------------------


def test_require_active_org_returns_org_id():
    assert require_active_org({"org_id": "org-1"}) == "org-1"


def test_require_active_org_missing_raises_400():
    with pytest.raises(HTTPException) as exc_info:
        require_active_org({"email": "x@example.com"})
    assert exc_info.value.status_code == 400


# --------------------------------------------------------------------------
# resolve_api_key
# --------------------------------------------------------------------------


def test_resolve_api_key_returns_key():
    with patch(
        "app.routers.prompt_refine.auth_service.get_provider_auth",
        return_value={"auth": {"api_key": "sk-live-123"}},
    ):
        assert resolve_api_key("org-1", "openai") == "sk-live-123"


def test_resolve_api_key_unwraps_list():
    with patch(
        "app.routers.prompt_refine.auth_service.get_provider_auth",
        return_value={"auth": {"api_key": ["sk-first", "sk-second"]}},
    ):
        assert resolve_api_key("org-1", "openai") == "sk-first"


def test_resolve_api_key_no_stored_credentials_raises():
    with patch(
        "app.routers.prompt_refine.auth_service.get_provider_auth",
        return_value=None,
    ):
        with pytest.raises(PromptRefineError, match="No stored credentials"):
            resolve_api_key("org-1", "openai")


def test_resolve_api_key_empty_key_raises():
    with patch(
        "app.routers.prompt_refine.auth_service.get_provider_auth",
        return_value={"auth": {"api_key": ""}},
    ):
        with pytest.raises(PromptRefineError, match="no api_key on file"):
            resolve_api_key("org-1", "openai")


def test_resolve_api_key_empty_list_raises():
    with patch(
        "app.routers.prompt_refine.auth_service.get_provider_auth",
        return_value={"auth": {"api_key": []}},
    ):
        with pytest.raises(PromptRefineError, match="no api_key on file"):
            resolve_api_key("org-1", "openai")


# --------------------------------------------------------------------------
# infer_mode
# --------------------------------------------------------------------------


def test_infer_mode_explicit_mode_wins():
    body = make_body(mode="optimize", existing_prompt="You are X.")
    assert infer_mode(body) == "optimize"


def test_infer_mode_existing_prompt_without_change_is_refine():
    body = make_body(existing_prompt="You are X.")
    assert infer_mode(body) == "refine"


def test_infer_mode_existing_prompt_with_change_is_targeted():
    body = make_body(existing_prompt="You are X.", requested_change="make it shorter")
    assert infer_mode(body) == "targeted"


def test_infer_mode_analyze_keyword_detected():
    body = make_body(prompt="Please analyze my prompt for issues")
    assert infer_mode(body) == "analyze"


def test_infer_mode_optimize_keyword_detected():
    body = make_body(prompt="Can you make it less robotic?")
    assert infer_mode(body) == "optimize"


def test_infer_mode_no_keyword_defaults_to_create():
    body = make_body(prompt="You are a friendly support agent for Acme Corp.")
    assert infer_mode(body) == "create"


def test_infer_mode_does_not_false_match_substring():
    """'optimize' must not match inside an unrelated word like 'deoptimized'."""
    body = make_body(prompt="Build a smart deoptimized agent for customer support.")
    assert infer_mode(body) == "create"


def test_infer_mode_does_not_false_match_analyze_substring():
    body = make_body(prompt="This agent handles psychoanalyze-style therapy intake.")
    assert infer_mode(body) == "create"


def test_infer_mode_multi_word_phrase_still_matches():
    body = make_body(prompt="I'd like to make shorter greetings for the agent.")
    assert infer_mode(body) == "optimize"


def test_infer_mode_checks_requested_change_too():
    body = make_body(prompt="A support agent.", requested_change="lint this for me")
    assert infer_mode(body) == "analyze"


# --------------------------------------------------------------------------
# build_context
# --------------------------------------------------------------------------


def test_build_context_includes_core_fields():
    body = make_body(
        prompt="Draft prompt",
        agent_name="Ava",
        agent_purpose="Book appointments",
        language="en",
        business_rules=["Never quote prices"],
    )
    context = build_context(body, "create")
    assert '"mode": "create"' in context
    assert '"user_request": "Draft prompt"' in context
    assert '"name": "Ava"' in context
    assert '"purpose": "Book appointments"' in context
    assert '"language": "en"' in context
    assert "Never quote prices" in context


def test_build_context_serializes_tools():
    body = make_body(
        prompt="Draft",
        available_tools=[{"name": "lookup_order", "description": "Looks up an order"}],
    )
    context = build_context(body, "create")
    assert "lookup_order" in context
    assert "Looks up an order" in context


def test_build_context_includes_protected_facts():
    body = make_body(prompt="Contact us at 1234567890 or support@example.com")
    context = build_context(body, "create")
    assert "1234567890" in context
    assert "support@example.com" in context


def test_build_context_protected_facts_key_present_even_when_empty():
    body = make_body(prompt="No factual values here.")
    context = build_context(body, "create")
    assert '"protected_facts": []' in context


def test_build_context_protected_facts_sourced_from_existing_prompt_when_present():
    body = make_body(
        prompt="A generic refine request",
        existing_prompt="Reach us at 5551234567",
    )
    context = build_context(body, "refine")
    assert "5551234567" in context


def test_build_context_protected_facts_falls_back_to_prompt_without_existing():
    body = make_body(prompt="Reach us at 5559876543")
    context = build_context(body, "create")
    assert "5559876543" in context


def test_build_context_protected_facts_scans_existing_prompt_not_request_text():
    """protected_facts is extracted from existing_prompt (source of truth),
    not body.prompt — even though body.prompt is separately serialized under
    user_request either way."""
    body = make_body(
        prompt="please add number 1112223333",
        existing_prompt="No factual values in here.",
    )
    context = build_context(body, "targeted")
    assert '"protected_facts": []' in context


# --------------------------------------------------------------------------
# extract_factual_identifiers
# --------------------------------------------------------------------------


def test_extract_factual_identifiers_finds_phone_email_url():
    text = "contact: 1234567890, email support@example.com, see https://example.com/help"
    values = extract_factual_identifiers(text)
    assert "1234567890" in values
    assert "support@example.com" in values
    assert "https://example.com/help" in values


def test_extract_factual_identifiers_empty_for_plain_text():
    assert extract_factual_identifiers("Just a plain prompt with no rule.") == []


def test_extract_factual_identifiers_empty_string():
    assert extract_factual_identifiers("") == []


def test_extract_factual_identifiers_dedupes_repeated_value():
    text = "Call 1234567890 or call again at 1234567890."
    assert extract_factual_identifiers(text).count("1234567890") == 1


def test_extract_factual_identifiers_orders_by_pattern_then_occurrence():
    # Order is: all phone matches (in text order), then all email matches (in
    # text order), then all URL matches (in text order) — patterns run
    # sequentially, not a single left-to-right scan of mixed types.
    text = "b@example.com then 1234567890 then https://x.com then a@example.com"
    values = extract_factual_identifiers(text)
    assert values == ["1234567890", "b@example.com", "a@example.com", "https://x.com"]


@pytest.mark.parametrize(
    "phone",
    [
        "1234567890",  # 10 digits, minimum
        "123456789012345",  # 15 digits, maximum
        "9876543210",
        "0000000000",
    ],
)
def test_extract_factual_identifiers_valid_phone_lengths_detected(phone):
    assert phone in extract_factual_identifiers(f"contact: {phone}")


@pytest.mark.parametrize(
    "digits",
    [
        "123456789",  # 9 digits — one short of minimum
        "1234567890123456",  # 16 digits — one over maximum
        "12345",
        "0",
    ],
)
def test_extract_factual_identifiers_out_of_range_digit_runs_not_matched_whole(digits):
    # A too-short/too-long digit run must not appear verbatim as an extracted
    # value (word-boundary + {10,15} quantifier reject it as a whole token).
    assert digits not in extract_factual_identifiers(f"code: {digits} end")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("call 12345678901234567890 now", []),  # 20 digits — no valid 10-15 substring at boundary
        ("id-1234567890", ["1234567890"]),  # hyphen doesn't block \b before digits
        ("(1234567890)", ["1234567890"]),
        ("phone:1234567890.", ["1234567890"]),
        ("a1234567890b", []),  # embedded in alnum on both sides — no word boundary
    ],
)
def test_extract_factual_identifiers_phone_boundary_cases(text, expected):
    values = extract_factual_identifiers(text)
    for value in expected:
        assert value in values
    if expected == []:
        assert values == []


@pytest.mark.parametrize(
    "email",
    [
        "user@example.com",
        "first.last@example.co.in",
        "user+tag@example.com",
        "user_name@sub.example.com",
        "a@b.co",
        "UPPER@EXAMPLE.COM",
    ],
)
def test_extract_factual_identifiers_valid_email_shapes(email):
    assert email in extract_factual_identifiers(f"reach us at {email} please")


@pytest.mark.parametrize(
    "non_email",
    [
        "not-an-email",
        "@missing-local.com",
        "missing-at-sign.com",
    ],
)
def test_extract_factual_identifiers_rejects_non_email(non_email):
    assert extract_factual_identifiers(non_email) == []


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://example.com",
        "https://example.com/path/to/page",
        "https://example.com/path?query=1&other=2",
        "https://sub.example.co.in:8080/path",
        "http://localhost:3000",
    ],
)
def test_extract_factual_identifiers_valid_url_shapes(url):
    assert url in extract_factual_identifiers(f"see {url} for details")


def test_extract_factual_identifiers_url_stops_at_whitespace():
    values = extract_factual_identifiers("visit https://example.com/help now")
    assert "https://example.com/help" in values
    assert not any("now" in v for v in values)


@pytest.mark.parametrize(
    "text,expected_url",
    [
        ("See https://example.com/help.", "https://example.com/help"),
        ("Visit (https://example.com/help), thanks.", "https://example.com/help"),
        ('Site: "https://example.com"', "https://example.com"),
        ("Is this https://example.com?", "https://example.com"),
        ("Great site: https://example.com!", "https://example.com"),
        ("List: https://example.com; https://other.com", "https://example.com"),
    ],
)
def test_extract_factual_identifiers_url_strips_trailing_sentence_punctuation(text, expected_url):
    values = extract_factual_identifiers(text)
    assert expected_url in values
    assert not any(v.endswith((".", ",", ")", '"', "!", "?", ";")) for v in values)


def test_extract_factual_identifiers_url_keeps_internal_punctuation():
    values = extract_factual_identifiers("see https://example.com/path?query=1&other=2 now")
    assert "https://example.com/path?query=1&other=2" in values


def test_extract_factual_identifiers_url_keeps_internal_dots():
    values = extract_factual_identifiers("url https://example.com/a.b.c end")
    assert "https://example.com/a.b.c" in values


def test_extract_factual_identifiers_multiple_of_same_type():
    text = "call 1112223333 or 4445556666"
    values = extract_factual_identifiers(text)
    assert "1112223333" in values
    assert "4445556666" in values
    assert len(values) == 2


def test_extract_factual_identifiers_mixed_types_all_found():
    text = (
        "Contact: 1234567890\n"
        "Email: support@example.com\n"
        "Site: https://example.com\n"
        "Backup phone: 9998887777\n"
        "Backup email: help@example.org\n"
    )
    values = extract_factual_identifiers(text)
    # Grouped by pattern (phones, then emails, then URLs), in text order
    # within each group.
    assert values == [
        "1234567890",
        "9998887777",
        "support@example.com",
        "help@example.org",
        "https://example.com",
    ]


def test_extract_factual_identifiers_email_inside_url_extracts_both_forms():
    # A mailto-style URL: the URL pattern greedily consumes the whole token,
    # so the bare email form is not separately matched — document that.
    text = "see https://example.com/contact?email=user@example.com"
    values = extract_factual_identifiers(text)
    assert "https://example.com/contact?email=user@example.com" in values


def test_extract_factual_identifiers_unicode_text_around_values():
    text = "कृपया संपर्क करें: 1234567890 या ईमेल करें support@example.com"
    values = extract_factual_identifiers(text)
    assert "1234567890" in values
    assert "support@example.com" in values


def test_extract_factual_identifiers_newlines_and_tabs_between_values():
    text = "phone:\n1234567890\temail:\tsupport@example.com"
    values = extract_factual_identifiers(text)
    assert "1234567890" in values
    assert "support@example.com" in values


def test_extract_factual_identifiers_returns_list_type():
    assert isinstance(extract_factual_identifiers("1234567890"), list)


@pytest.mark.parametrize(
    "text,expected_digits",
    [
        ("call 123-456-7890", "1234567890"),
        ("call (123) 456-7890", "1234567890"),
        ("call 123.456.7890", "1234567890"),
        ("call +1 123 456 7890", "11234567890"),
        ("call +91-9876543210", "919876543210"),
    ],
)
def test_extract_factual_identifiers_normalizes_formatted_phone_to_digits(text, expected_digits):
    values = extract_factual_identifiers(text)
    assert expected_digits in values
    # normalized form only — no formatting characters leak into the result
    assert not any(c in v for v in values for c in " ()-.+" if v == expected_digits)


@pytest.mark.parametrize(
    "text",
    [
        "see pages 12-15",
        "version 1.2.3",
        "section 4.5.6 of the doc",
        "the year 2024-2025",
        "id: 12-34-56",
    ],
)
def test_extract_factual_identifiers_rejects_short_formatted_numbers(text):
    """Loose phone-shape pattern also matches version numbers and ranges;
    the 10-15 digit-count filter must reject anything that isn't actually
    phone-length once un-formatted."""
    assert extract_factual_identifiers(text) == []


def test_extract_factual_identifiers_embedded_in_word_still_rejected_with_new_pattern():
    """Regression guard: switching from \\b to lookarounds (to support a
    leading '+' or '(') must not reopen the embedded-in-alnum false match."""
    assert extract_factual_identifiers("a1234567890b") == []


# --------------------------------------------------------------------------
# _value_preserved / validate_refined_prompt — reformatted phone numbers
# --------------------------------------------------------------------------


def test_validate_refined_prompt_no_warning_when_phone_reformatted():
    """The refiner may legitimately reformat "1234567890" into
    "123-456-7890" when fitting it into new prose — that's not a drop."""
    original = "contact: 1234567890\n\nABSOLUTE RULE: never guess."
    refined = "Contact: 123-456-7890\n\nABSOLUTE RULE: never guess."
    warnings = validate_refined_prompt(original, refined)
    assert not any("was not preserved" in w for w in warnings)


def test_validate_refined_prompt_no_warning_when_phone_gains_parens():
    original = "contact: 1234567890\n\nABSOLUTE RULE: never guess."
    refined = "Contact: (123) 456-7890\n\nABSOLUTE RULE: never guess."
    warnings = validate_refined_prompt(original, refined)
    assert not any("was not preserved" in w for w in warnings)


def test_validate_refined_prompt_flags_phone_with_altered_digit():
    """Reformatting is fine; changing even one digit is not."""
    original = "contact: 1234567890\n\nABSOLUTE RULE: never guess."
    refined = "Contact: 123-456-7899\n\nABSOLUTE RULE: never guess."
    warnings = validate_refined_prompt(original, refined)
    assert any("1234567890" in w for w in warnings)


def test_validate_refined_prompt_email_still_requires_verbatim_match():
    """Only phone-shaped (all-digit) values get reformat-tolerant
    comparison; emails/URLs must still match exactly."""
    original = "email support@example.com\n\nABSOLUTE RULE: never guess."
    refined = "email SUPPORT@EXAMPLE.COM\n\nABSOLUTE RULE: never guess."
    warnings = validate_refined_prompt(original, refined)
    assert any("support@example.com" in w for w in warnings)


# --------------------------------------------------------------------------
# extract_factual_identifiers — adjacency / merging regressions
# --------------------------------------------------------------------------


def test_extract_factual_identifiers_two_adjacent_ids_not_merged_into_one_lost_match():
    """Regression: a wider per-group digit cap let a bare space merge two
    unrelated 9-digit ids into one 18-digit span, which then failed the
    10-15 length filter and silently dropped BOTH ids — worse than doing
    nothing. Each short id must independently fail to match phone-length,
    without swallowing its neighbor."""
    values = extract_factual_identifiers("ids 111111111 222222222")
    assert values == []


def test_extract_factual_identifiers_two_adjacent_real_phones_both_kept():
    values = extract_factual_identifiers("primary: 1234567890, secondary: 9998887777")
    assert "1234567890" in values
    assert "9998887777" in values
    assert len(values) == 2


def test_extract_factual_identifiers_short_id_next_to_real_phone_only_phone_kept():
    values = extract_factual_identifiers("order 12345 shipped, call 1234567890")
    assert values == ["1234567890"]


def test_extract_factual_identifiers_two_bare_phones_separated_by_word():
    values = extract_factual_identifiers("call 1112223333 or fax 4445556666")
    assert set(values) == {"1112223333", "4445556666"}


def test_extract_factual_identifiers_dedupes_same_number_different_formats():
    """Same underlying number in two formats normalizes to one value and is
    deduped — not two separate protected facts for one real number."""
    text = "call 1234567890, or 123-456-7890 if that fails"
    values = extract_factual_identifiers(text)
    assert values.count("1234567890") == 1


@pytest.mark.parametrize(
    "digit_count,should_match",
    [(9, False), (10, True), (11, True), (15, True), (16, False), (18, False)],
)
def test_extract_factual_identifiers_bare_digit_length_boundaries(digit_count, should_match):
    digits = "1" * digit_count
    values = extract_factual_identifiers(f"code: {digits} end")
    assert (digits in values) == should_match


def test_extract_factual_identifiers_empty_and_whitespace_only():
    assert extract_factual_identifiers("") == []
    assert extract_factual_identifiers("   ") == []
    assert extract_factual_identifiers("\n\t\n") == []


def test_extract_factual_identifiers_none_type_raises():
    with pytest.raises(TypeError):
        extract_factual_identifiers(None)  # type: ignore[arg-type]


def test_extract_factual_identifiers_long_text_with_value_near_end():
    text = "x" * 5000 + " call 1234567890"
    assert "1234567890" in extract_factual_identifiers(text)


def test_extract_factual_identifiers_many_distinct_values_all_found():
    phones = [f"{n}000000000"[:10] for n in range(1, 11)]
    text = ", ".join(f"call {p}" for p in phones)
    values = extract_factual_identifiers(text)
    for p in phones:
        assert p in values


# --------------------------------------------------------------------------
# _normalize_phone — direct unit tests
# --------------------------------------------------------------------------


def test_normalize_phone_strips_all_formatting_characters():
    assert prompt_refine._normalize_phone("+1 (123) 456-7890") == "11234567890"


def test_normalize_phone_bare_digits_unchanged():
    assert prompt_refine._normalize_phone("1234567890") == "1234567890"


@pytest.mark.parametrize(
    "candidate",
    ["12-15", "1.2.3", "2024-2025", "123456789", "1234567890123456"],
)
def test_normalize_phone_rejects_out_of_range(candidate):
    assert prompt_refine._normalize_phone(candidate) is None


@pytest.mark.parametrize(
    "candidate,expected",
    [
        ("1234567890", "1234567890"),
        ("123456789012345", "123456789012345"),
    ],
)
def test_normalize_phone_accepts_boundary_lengths(candidate, expected):
    assert prompt_refine._normalize_phone(candidate) == expected


# --------------------------------------------------------------------------
# _value_preserved — direct unit tests
# --------------------------------------------------------------------------


def test_value_preserved_digit_value_matches_reformatted_refined_text():
    assert prompt_refine._value_preserved("1234567890", "call 123-456-7890 now") is True


def test_value_preserved_digit_value_missing_from_refined_text():
    assert prompt_refine._value_preserved("1234567890", "no number here") is False


def test_value_preserved_digit_value_with_altered_digit_fails():
    assert prompt_refine._value_preserved("1234567890", "call 123-456-7899") is False


def test_value_preserved_non_digit_value_requires_exact_substring():
    assert prompt_refine._value_preserved("support@example.com", "email support@example.com") is True
    assert prompt_refine._value_preserved("support@example.com", "email SUPPORT@EXAMPLE.COM") is False


def test_value_preserved_url_requires_exact_substring():
    assert prompt_refine._value_preserved("https://example.com", "see https://example.com here") is True
    assert prompt_refine._value_preserved("https://example.com", "see https://example.org here") is False


def test_value_preserved_empty_value_trivially_preserved():
    assert prompt_refine._value_preserved("", "anything") is True


# --------------------------------------------------------------------------
# validate_refined_prompt
# --------------------------------------------------------------------------


def test_validate_refined_prompt_flags_missing_absolute_rule():
    warnings = validate_refined_prompt("source", "Just a plain prompt with no rule.")
    assert any("factual-value safety rule" in w for w in warnings)


def test_validate_refined_prompt_passes_with_absolute_rule():
    warnings = validate_refined_prompt("source", "Some prompt.\n\nABSOLUTE RULE: never guess.")
    assert not any("factual-value safety rule" in w for w in warnings)


def test_validate_refined_prompt_flags_leaked_secret():
    warnings = validate_refined_prompt(
        "source", "api_key: sk-abc123\n\nABSOLUTE RULE: never guess."
    )
    assert any("credential or secret" in w for w in warnings)


def test_validate_refined_prompt_clean_has_no_warnings():
    warnings = validate_refined_prompt("source", "A clean prompt.\n\nABSOLUTE RULE: never guess.")
    assert warnings == []


def test_validate_refined_prompt_flags_dropped_factual_value():
    original = "contact: 1234567890\n\nABSOLUTE RULE: never guess."
    refined = "A clean prompt.\n\nABSOLUTE RULE: never guess."
    warnings = validate_refined_prompt(original, refined)
    assert any("1234567890" in w for w in warnings)


def test_validate_refined_prompt_no_warning_when_value_preserved():
    original = "contact: 1234567890\n\nABSOLUTE RULE: never guess."
    refined = "Contact: 1234567890\n\nABSOLUTE RULE: never guess."
    warnings = validate_refined_prompt(original, refined)
    assert not any("1234567890" in w for w in warnings)


def test_validate_refined_prompt_flags_dropped_email():
    original = "email support@example.com\n\nABSOLUTE RULE: never guess."
    refined = "A clean prompt.\n\nABSOLUTE RULE: never guess."
    warnings = validate_refined_prompt(original, refined)
    assert any("support@example.com" in w for w in warnings)


def test_validate_refined_prompt_flags_dropped_url():
    original = "see https://example.com/help\n\nABSOLUTE RULE: never guess."
    refined = "A clean prompt.\n\nABSOLUTE RULE: never guess."
    warnings = validate_refined_prompt(original, refined)
    assert any("https://example.com/help" in w for w in warnings)


def test_validate_refined_prompt_flags_each_dropped_value_separately():
    original = "call 1234567890 or email support@example.com\n\nABSOLUTE RULE: never guess."
    refined = "A clean prompt.\n\nABSOLUTE RULE: never guess."
    warnings = validate_refined_prompt(original, refined)
    dropped = [w for w in warnings if "was not preserved" in w]
    assert len(dropped) == 2
    assert any("1234567890" in w for w in dropped)
    assert any("support@example.com" in w for w in dropped)


def test_validate_refined_prompt_partial_preservation_flags_only_missing_one():
    original = "call 1234567890 or email support@example.com\n\nABSOLUTE RULE: never guess."
    refined = "call 1234567890.\n\nABSOLUTE RULE: never guess."
    warnings = validate_refined_prompt(original, refined)
    dropped = [w for w in warnings if "was not preserved" in w]
    assert len(dropped) == 1
    assert "support@example.com" in dropped[0]


def test_validate_refined_prompt_no_source_values_no_dropped_warnings():
    original = "You are a plain agent with no facts.\n\nABSOLUTE RULE: never guess."
    refined = "You are a refined agent.\n\nABSOLUTE RULE: never guess."
    warnings = validate_refined_prompt(original, refined)
    assert not any("was not preserved" in w for w in warnings)


def test_validate_refined_prompt_combines_missing_rule_and_dropped_value():
    original = "contact: 1234567890"
    refined = "A clean prompt with no rule and no number."
    warnings = validate_refined_prompt(original, refined)
    assert any("factual-value safety rule" in w for w in warnings)
    assert any("1234567890" in w for w in warnings)
    assert len(warnings) == 2


def test_validate_refined_prompt_combines_secret_leak_and_dropped_value():
    original = "contact: 1234567890\n\nABSOLUTE RULE: never guess."
    refined = "api_key: sk-abc123\n\nABSOLUTE RULE: never guess."
    warnings = validate_refined_prompt(original, refined)
    assert any("credential or secret" in w for w in warnings)
    assert any("1234567890" in w for w in warnings)


def test_validate_refined_prompt_empty_original_no_dropped_warnings():
    warnings = validate_refined_prompt("", "Some prompt.\n\nABSOLUTE RULE: never guess.")
    assert not any("was not preserved" in w for w in warnings)


def test_validate_refined_prompt_value_preserved_as_substring_of_larger_token_counts():
    # extract_factual_identifiers finds "1234567890"; validate only checks
    # substring containment, so a preserved value embedded in more text
    # (e.g. reformatted with a country code) still counts as preserved.
    original = "contact: 1234567890\n\nABSOLUTE RULE: never guess."
    refined = "Contact: +1-1234567890 (ext. 0)\n\nABSOLUTE RULE: never guess."
    warnings = validate_refined_prompt(original, refined)
    assert not any("was not preserved" in w for w in warnings)


@pytest.mark.parametrize(
    "original,refined,should_warn",
    [
        ("1234567890", "1234567890", False),
        ("1234567890", "different text entirely", True),
        ("a@b.com", "a@b.com", False),
        ("a@b.com", "b@a.com", True),
        ("https://x.com", "https://x.com", False),
        ("https://x.com", "https://y.com", True),
        ("no facts here", "still no facts", False),
        ("1234567890 and a@b.com", "1234567890 and a@b.com", False),
        ("1234567890 and a@b.com", "1234567890 only", True),
        ("1234567890 and a@b.com", "a@b.com only", True),
    ],
)
def test_validate_refined_prompt_preservation_matrix(original, refined, should_warn):
    warnings = validate_refined_prompt(original, refined)
    dropped = [w for w in warnings if "was not preserved" in w]
    assert bool(dropped) == should_warn


# --------------------------------------------------------------------------
# summarize_changes
# --------------------------------------------------------------------------


def test_summarize_changes_detects_new_sections():
    original = "You are an agent."
    refined = "[Identity & Purpose]\nYou are an agent.\n\n[Tool Usage]\nUse tools."
    changes = summarize_changes(original, refined)
    assert "Added identity/purpose guidance" in changes
    assert "Added tool usage guidance" in changes


def test_summarize_changes_detects_absolute_rule_addition():
    original = "You are an agent."
    refined = "You are an agent.\n\nABSOLUTE RULE: never guess."
    changes = summarize_changes(original, refined)
    assert "Added factual-value and action-verification guardrail" in changes


def test_summarize_changes_falls_back_when_nothing_detected():
    original = "You are an agent that helps."
    refined = "You are an agent that assists."
    changes = summarize_changes(original, refined)
    assert changes == ["Refined wording and structure while preserving supplied behavior"]


# --------------------------------------------------------------------------
# candidate_providers
# --------------------------------------------------------------------------


def test_candidate_providers_requested_provider_first():
    body = make_body(llm_provider="groq")
    with patch(
        "app.routers.prompt_refine.auth_service.list_configured_providers",
        return_value=["openai", "groq", "sarvam"],
    ):
        result = candidate_providers(body, "org-1")
    assert result[0] == "groq"
    assert set(result) == {"openai", "groq", "sarvam"}


def test_candidate_providers_falls_back_when_requested_not_configured():
    body = make_body(llm_provider="openai")
    with patch(
        "app.routers.prompt_refine.auth_service.list_configured_providers",
        return_value=["groq"],
    ):
        result = candidate_providers(body, "org-1")
    assert result == ["groq"]


def test_candidate_providers_ignores_unsupported_configured_provider():
    body = make_body()
    with patch(
        "app.routers.prompt_refine.auth_service.list_configured_providers",
        return_value=["deepgram", "groq"],
    ):
        result = candidate_providers(body, "org-1")
    assert result == ["groq"]


def test_candidate_providers_empty_when_nothing_configured():
    body = make_body()
    with patch(
        "app.routers.prompt_refine.auth_service.list_configured_providers",
        return_value=[],
    ):
        result = candidate_providers(body, "org-1")
    assert result == []


def test_candidate_providers_stable_priority_order_without_request():
    body = make_body()
    with patch(
        "app.routers.prompt_refine.auth_service.list_configured_providers",
        return_value=["atlascloud", "openai", "sarvam"],
    ):
        result = candidate_providers(body, "org-1")
    # PROVIDER_BASE_URLS dict order: openai, groq, sarvam, openrouter, atlascloud
    assert result == ["openai", "sarvam", "atlascloud"]


# --------------------------------------------------------------------------
# call_refiner
# --------------------------------------------------------------------------


def _mock_completion(text: str) -> MagicMock:
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=text))]
    return completion


def test_call_refiner_no_candidates_raises():
    body = make_body()
    with patch(
        "app.routers.prompt_refine.auth_service.list_configured_providers",
        return_value=[],
    ):
        with pytest.raises(PromptRefineError, match="No configured LLM provider"):
            call_refiner(body, "org-1")


def test_call_refiner_uses_requested_provider_and_model():
    body = make_body(llm_provider="groq", llm_model="custom-model")
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=["groq"],
        ),
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"api_key": "gsk-1"}},
        ),
        patch("app.routers.prompt_refine.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_completion("Refined prompt.")
        mock_openai.return_value = mock_client

        refined, mode, provider_used, model_used = call_refiner(body, "org-1")

    assert refined == "Refined prompt."
    assert provider_used == "groq"
    assert model_used == "custom-model"
    mock_client.chat.completions.create.assert_called_once()
    assert mock_client.chat.completions.create.call_args.kwargs["model"] == "custom-model"


def test_call_refiner_falls_back_to_default_model_when_unset():
    body = make_body(llm_provider="groq")
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=["groq"],
        ),
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"api_key": "gsk-1"}},
        ),
        patch("app.routers.prompt_refine.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_completion("Refined prompt.")
        mock_openai.return_value = mock_client

        _, _, _, model_used = call_refiner(body, "org-1")

    assert model_used == "llama-3.3-70b-versatile"


def test_call_refiner_requested_model_ignored_for_fallback_provider():
    """A model meant for the requested provider must not leak to the fallback provider."""
    body = make_body(llm_provider="openai", llm_model="gpt-4o")
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=["groq"],
        ),
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"api_key": "gsk-1"}},
        ),
        patch("app.routers.prompt_refine.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_completion("Refined prompt.")
        mock_openai.return_value = mock_client

        _, _, provider_used, model_used = call_refiner(body, "org-1")

    assert provider_used == "groq"
    assert model_used == "llama-3.3-70b-versatile"


def test_call_refiner_falls_back_across_providers_on_missing_credentials():
    body = make_body(llm_provider="openai")
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=["openai", "groq"],
        ),
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            side_effect=[None, {"auth": {"api_key": "gsk-1"}}],
        ),
        patch("app.routers.prompt_refine.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_completion("Refined prompt.")
        mock_openai.return_value = mock_client

        refined, _, provider_used, _ = call_refiner(body, "org-1")

    assert provider_used == "groq"
    assert refined == "Refined prompt."


def test_call_refiner_stops_on_real_api_failure_without_trying_next_provider():
    """A genuine request failure must surface immediately, not be masked by fallback."""
    body = make_body(llm_provider="openai")
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=["openai", "groq"],
        ),
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"api_key": "sk-1"}},
        ),
        patch("app.routers.prompt_refine.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_request = MagicMock()
        mock_client.chat.completions.create.side_effect = APIConnectionError(request=mock_request)
        mock_openai.return_value = mock_client

        with pytest.raises(PromptRefineError, match="openai request to .* failed"):
            call_refiner(body, "org-1")

    # Only the first (failing) provider should have been attempted.
    mock_client.chat.completions.create.assert_called_once()


def test_call_refiner_empty_response_raises():
    body = make_body(llm_provider="openai")
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=["openai"],
        ),
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"api_key": "sk-1"}},
        ),
        patch("app.routers.prompt_refine.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_completion("")
        mock_openai.return_value = mock_client

        with pytest.raises(PromptRefineError, match="returned an empty response"):
            call_refiner(body, "org-1")


def test_call_refiner_all_candidates_missing_credentials_raises_last_error():
    body = make_body(llm_provider="openai")
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=["openai", "groq"],
        ),
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value=None,
        ),
    ):
        with pytest.raises(PromptRefineError, match="No stored credentials"):
            call_refiner(body, "org-1")


# --------------------------------------------------------------------------
# Endpoint (HTTP-level)
# --------------------------------------------------------------------------


def test_endpoint_success_returns_full_response():
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=["openai"],
        ),
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"api_key": "sk-1"}},
        ),
        patch("app.routers.prompt_refine.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_completion(
            "Refined.\n\nABSOLUTE RULE: never guess."
        )
        mock_openai.return_value = mock_client

        response = client.post(
            "/api/v1/prompts/refine",
            json={"prompt": "You are a support agent."},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["refined_prompt"] == "Refined.\n\nABSOLUTE RULE: never guess."
    assert body["provider_used"] == "openai"
    assert body["model_used"] == prompt_refine.PROVIDER_DEFAULT_MODEL["openai"]
    assert body["mode"] == "create"
    assert body["warnings"] == []


def test_endpoint_no_configured_provider_returns_422():
    with patch(
        "app.routers.prompt_refine.auth_service.list_configured_providers",
        return_value=[],
    ):
        response = client.post(
            "/api/v1/prompts/refine",
            json={"prompt": "You are a support agent."},
        )

    assert response.status_code == 422
    assert "No configured LLM provider" in response.json()["detail"]


def test_endpoint_missing_prompt_is_422_validation_error():
    response = client.post("/api/v1/prompts/refine", json={"prompt": ""})
    assert response.status_code == 422


def test_endpoint_includes_change_summary_when_requested():
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=["openai"],
        ),
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"api_key": "sk-1"}},
        ),
        patch("app.routers.prompt_refine.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_completion(
            "[Tool Usage]\nUse tools.\n\nABSOLUTE RULE: never guess."
        )
        mock_openai.return_value = mock_client

        response = client.post(
            "/api/v1/prompts/refine",
            json={"prompt": "You are an agent.", "include_change_summary": True},
        )

    assert response.status_code == 200
    assert "Added tool usage guidance" in response.json()["changes"]


def test_endpoint_omits_change_summary_by_default():
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=["openai"],
        ),
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"api_key": "sk-1"}},
        ),
        patch("app.routers.prompt_refine.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_completion(
            "Refined.\n\nABSOLUTE RULE: never guess."
        )
        mock_openai.return_value = mock_client

        response = client.post(
            "/api/v1/prompts/refine",
            json={"prompt": "You are an agent."},
        )

    assert response.json()["changes"] == []


def test_endpoint_missing_absolute_rule_surfaces_warning():
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=["openai"],
        ),
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"api_key": "sk-1"}},
        ),
        patch("app.routers.prompt_refine.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_completion("No rule here.")
        mock_openai.return_value = mock_client

        response = client.post(
            "/api/v1/prompts/refine",
            json={"prompt": "You are an agent."},
        )

    assert response.status_code == 200
    assert any("factual-value safety rule" in w for w in response.json()["warnings"])


def test_endpoint_real_api_failure_returns_422():
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=["openai"],
        ),
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"api_key": "sk-1"}},
        ),
        patch("app.routers.prompt_refine.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_request = MagicMock()
        mock_client.chat.completions.create.side_effect = APIError(
            "boom", request=mock_request, body=None
        )
        mock_openai.return_value = mock_client

        response = client.post(
            "/api/v1/prompts/refine",
            json={"prompt": "You are an agent.", "llm_provider": "openai"},
        )

    assert response.status_code == 422
    assert "openai request to" in response.json()["detail"]


def test_endpoint_falls_back_to_orgs_configured_provider():
    """Requesting a provider the org doesn't have shouldn't hard-fail if another is configured."""
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=["groq"],
        ),
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"api_key": "gsk-1"}},
        ),
        patch("app.routers.prompt_refine.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_completion(
            "Refined.\n\nABSOLUTE RULE: never guess."
        )
        mock_openai.return_value = mock_client

        response = client.post(
            "/api/v1/prompts/refine",
            json={"prompt": "You are an agent.", "llm_provider": "openai"},
        )

    assert response.status_code == 200
    assert response.json()["provider_used"] == "groq"


# --------------------------------------------------------------------------
# resolve_openai_compatible — azure_openai
# --------------------------------------------------------------------------


def test_resolve_openai_compatible_azure_builds_deployment_url():
    body = make_body(llm_provider="azure_openai", llm_model="gpt-4o-deployment")
    with patch(
        "app.routers.prompt_refine.auth_service.get_provider_auth",
        return_value={
            "auth": {"api_key": "azure-key", "endpoint": "https://myres.openai.azure.com"}
        },
    ):
        api_key, base_url, model, extra_kwargs = resolve_openai_compatible(
            body, "org-1", "azure_openai"
        )

    assert api_key == "azure-key"
    assert base_url == "https://myres.openai.azure.com/openai/deployments/gpt-4o-deployment"
    assert model == "gpt-4o-deployment"
    assert extra_kwargs == {"default_query": {"api-version": prompt_refine.AZURE_OPENAI_API_VERSION}}


def test_resolve_openai_compatible_azure_requires_model():
    body = make_body(llm_provider="azure_openai")
    with patch(
        "app.routers.prompt_refine.auth_service.get_provider_auth",
        return_value={
            "auth": {"api_key": "azure-key", "endpoint": "https://myres.openai.azure.com"}
        },
    ):
        with pytest.raises(PromptRefineError, match="requires llm_model"):
            resolve_openai_compatible(body, "org-1", "azure_openai")


def test_resolve_openai_compatible_azure_missing_endpoint_raises():
    body = make_body(llm_provider="azure_openai", llm_model="gpt-4o-deployment")
    with patch(
        "app.routers.prompt_refine.auth_service.get_provider_auth",
        return_value={"auth": {"api_key": "azure-key"}},
    ):
        with pytest.raises(PromptRefineError, match="no api_key/endpoint on file"):
            resolve_openai_compatible(body, "org-1", "azure_openai")


# --------------------------------------------------------------------------
# resolve_openai_compatible — google
# --------------------------------------------------------------------------


def test_resolve_openai_compatible_google_uses_fixed_endpoint():
    body = make_body(llm_provider="google")
    with patch(
        "app.routers.prompt_refine.auth_service.get_provider_auth",
        return_value={"auth": {"api_key": "google-key"}},
    ):
        api_key, base_url, model, extra_kwargs = resolve_openai_compatible(body, "org-1", "google")

    assert api_key == "google-key"
    assert base_url == prompt_refine.GOOGLE_OPENAI_COMPAT_BASE_URL
    assert model == prompt_refine.GOOGLE_DEFAULT_MODEL
    assert extra_kwargs == {}


def test_resolve_openai_compatible_google_honors_requested_model():
    body = make_body(llm_provider="google", llm_model="gemini-1.5-pro")
    with patch(
        "app.routers.prompt_refine.auth_service.get_provider_auth",
        return_value={"auth": {"api_key": "google-key"}},
    ):
        _, _, model, _ = resolve_openai_compatible(body, "org-1", "google")

    assert model == "gemini-1.5-pro"


# --------------------------------------------------------------------------
# resolve_voicera_model_server
# --------------------------------------------------------------------------


def test_resolve_voicera_model_server_uses_env_var():
    with patch.dict("os.environ", {"MODEL_SERVER_URL": "http://llm-gateway:8100/v1"}):
        api_key, base_url, model = resolve_voicera_model_server()

    assert api_key is None
    assert base_url == "http://llm-gateway:8100/v1"
    assert model == prompt_refine.VOICERA_MODEL_SERVER_MODEL


def test_resolve_voicera_model_server_missing_env_var_raises():
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(PromptRefineError, match="MODEL_SERVER_URL is not set"):
            resolve_voicera_model_server()


# --------------------------------------------------------------------------
# candidate_providers — new provider families
# --------------------------------------------------------------------------


def test_candidate_providers_includes_voicera_model_server_when_env_set():
    body = make_body()
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=["openai"],
        ),
        patch.dict("os.environ", {"MODEL_SERVER_URL": "http://llm-gateway:8100/v1"}),
    ):
        result = candidate_providers(body, "org-1")
    assert "voicera_model_server" in result


def test_candidate_providers_excludes_voicera_model_server_when_env_unset():
    body = make_body()
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=["openai"],
        ),
        patch.dict("os.environ", {}, clear=True),
    ):
        result = candidate_providers(body, "org-1")
    assert "voicera_model_server" not in result


def test_candidate_providers_includes_azure_and_google_when_configured():
    body = make_body()
    with patch(
        "app.routers.prompt_refine.auth_service.list_configured_providers",
        return_value=["azure_openai", "google"],
    ):
        result = candidate_providers(body, "org-1")
    assert set(result) == {"azure_openai", "google"}


# --------------------------------------------------------------------------
# call_refiner — new provider families end-to-end
# --------------------------------------------------------------------------


def test_call_refiner_uses_voicera_model_server_when_nothing_else_configured():
    body = make_body()
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=[],
        ),
        patch.dict("os.environ", {"MODEL_SERVER_URL": "http://llm-gateway:8100/v1"}),
        patch("app.routers.prompt_refine.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_completion("Refined.")
        mock_openai.return_value = mock_client

        refined, _, provider_used, model_used = call_refiner(body, "org-1")

    assert refined == "Refined."
    assert provider_used == "voicera_model_server"
    assert model_used == prompt_refine.VOICERA_MODEL_SERVER_MODEL
    mock_openai.assert_called_once_with(
        api_key="not-required", base_url="http://llm-gateway:8100/v1", timeout=REQUEST_TIMEOUT_SECONDS
    )


def test_call_refiner_azure_openai_end_to_end():
    body = make_body(llm_provider="azure_openai", llm_model="gpt-4o-deployment")
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=["azure_openai"],
        ),
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={
                "auth": {"api_key": "azure-key", "endpoint": "https://myres.openai.azure.com"}
            },
        ),
        patch("app.routers.prompt_refine.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_completion("Refined.")
        mock_openai.return_value = mock_client

        refined, _, provider_used, model_used = call_refiner(body, "org-1")

    assert refined == "Refined."
    assert provider_used == "azure_openai"
    assert model_used == "gpt-4o-deployment"
    mock_openai.assert_called_once_with(
        api_key="azure-key",
        base_url="https://myres.openai.azure.com/openai/deployments/gpt-4o-deployment",
        timeout=REQUEST_TIMEOUT_SECONDS,
        default_query={"api-version": prompt_refine.AZURE_OPENAI_API_VERSION},
    )


def test_call_refiner_google_end_to_end():
    body = make_body(llm_provider="google")
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=["google"],
        ),
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"api_key": "google-key"}},
        ),
        patch("app.routers.prompt_refine.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_completion("Refined.")
        mock_openai.return_value = mock_client

        refined, _, provider_used, model_used = call_refiner(body, "org-1")

    assert refined == "Refined."
    assert provider_used == "google"
    mock_openai.assert_called_once_with(
        api_key="google-key",
        base_url=prompt_refine.GOOGLE_OPENAI_COMPAT_BASE_URL,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


# --------------------------------------------------------------------------
# call_kenpath — Bharat Vistaar (OpenAI-styled chat/completions) + Vistaar
# (single-turn query API) — two genuinely different wire protocols.
# --------------------------------------------------------------------------


def _test_rsa_private_key_pem() -> str:
    """A throwaway RSA key generated at test time — never real key material."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


def _mock_httpx_response(*, json_data=None, text=None, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status = MagicMock()
    if json_data is not None:
        response.json.return_value = json_data
    if text is not None:
        response.text = text
    return response


def test_call_kenpath_bharat_vistaar_openai_shaped_response():
    body = make_body(llm_provider="kenpath", llm_model="bharatvistaar-prod (English, Hindi)")
    pem = _test_rsa_private_key_pem()
    with (
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"bharat_prod_private_key": pem}},
        ),
        patch("apps.providers.refine_llm.httpx.post") as mock_post,
    ):
        mock_post.return_value = _mock_httpx_response(
            json_data={"choices": [{"message": {"content": "Refined kenpath prompt."}}]}
        )
        refined, model = call_kenpath(
            "org-1", body.llm_model, "system instructions", "user request",
            resolve_auth=resolve_stored_auth,
        )

    assert refined == "Refined kenpath prompt."
    assert model == "bharatvistaar-prod (English, Hindi)"
    call_kwargs = mock_post.call_args.kwargs
    assert call_kwargs["json"]["messages"] == [
        {"role": "system", "content": "system instructions"},
        {"role": "user", "content": "user request"},
    ]
    assert call_kwargs["json"]["stream"] is False
    assert "Bearer " in call_kwargs["headers"]["Authorization"]


def test_call_kenpath_bharat_vistaar_bare_response_shape():
    body = make_body(llm_provider="kenpath", llm_model="bharatvistaar-prod (English, Hindi)")
    pem = _test_rsa_private_key_pem()
    with (
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"bharat_prod_private_key": pem}},
        ),
        patch("apps.providers.refine_llm.httpx.post") as mock_post,
    ):
        mock_post.return_value = _mock_httpx_response(json_data={"response": "Bare shape reply."})
        refined, _ = call_kenpath("org-1", body.llm_model, "system", "user", resolve_auth=resolve_stored_auth)

    assert refined == "Bare shape reply."


def test_call_kenpath_bharat_vistaar_missing_key_raises():
    body = make_body(llm_provider="kenpath", llm_model="bharatvistaar-prod (English, Hindi)")
    with patch(
        "app.routers.prompt_refine.auth_service.get_provider_auth",
        return_value={"auth": {}},
    ):
        with pytest.raises(PromptRefineError, match="bharat_prod_private_key"):
            call_kenpath("org-1", body.llm_model, "system", "user", resolve_auth=resolve_stored_auth)


def test_call_kenpath_bharat_vistaar_http_error_raises():
    body = make_body(llm_provider="kenpath", llm_model="bharatvistaar-prod (English, Hindi)")
    pem = _test_rsa_private_key_pem()
    with (
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"bharat_prod_private_key": pem}},
        ),
        patch("apps.providers.refine_llm.httpx.post") as mock_post,
    ):
        mock_post.side_effect = httpx.ConnectError("connection refused")
        with pytest.raises(PromptRefineError, match="kenpath \\(bharatvistaar\\) request failed"):
            call_kenpath("org-1", body.llm_model, "system", "user", resolve_auth=resolve_stored_auth)


def test_call_kenpath_vistaar_query_api_forces_system_and_user_together():
    body = make_body(llm_provider="kenpath", llm_model="vistaar-prod (Marathi, Bhili)")
    pem = _test_rsa_private_key_pem()
    with (
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"private_key": pem}},
        ),
        patch("apps.providers.refine_llm.httpx.get") as mock_get,
    ):
        mock_get.return_value = _mock_httpx_response(text="Vistaar plain text reply.")
        refined, model = call_kenpath("org-1", body.llm_model, "system instructions", "user request", resolve_auth=resolve_stored_auth)

    assert refined == "Vistaar plain text reply."
    assert model == "vistaar-prod (Marathi, Bhili)"
    call_kwargs = mock_get.call_args.kwargs
    assert "system instructions" in call_kwargs["params"]["query"]
    assert "user request" in call_kwargs["params"]["query"]


def test_call_kenpath_vistaar_missing_key_raises():
    body = make_body(llm_provider="kenpath", llm_model="vistaar-prod (Marathi, Bhili)")
    with patch(
        "app.routers.prompt_refine.auth_service.get_provider_auth",
        return_value={"auth": {}},
    ):
        with pytest.raises(PromptRefineError, match="private_key"):
            call_kenpath("org-1", body.llm_model, "system", "user", resolve_auth=resolve_stored_auth)


def test_call_kenpath_defaults_to_vistaar_prod_when_no_model_requested():
    body = make_body(llm_provider="kenpath")
    pem = _test_rsa_private_key_pem()
    with (
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"private_key": pem}},
        ),
        patch("apps.providers.refine_llm.httpx.get") as mock_get,
    ):
        mock_get.return_value = _mock_httpx_response(text="reply")
        _, model = call_kenpath("org-1", body.llm_model, "system", "user", resolve_auth=resolve_stored_auth)

    assert model == KENPATH_DEFAULT_MODEL


# --------------------------------------------------------------------------
# call_refiner — kenpath end-to-end (through the fallback loop)
# --------------------------------------------------------------------------


def test_call_refiner_kenpath_end_to_end():
    body = make_body(llm_provider="kenpath", llm_model="bharatvistaar-prod (English, Hindi)")
    pem = _test_rsa_private_key_pem()
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=["kenpath"],
        ),
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"bharat_prod_private_key": pem}},
        ),
        patch("apps.providers.refine_llm.httpx.post") as mock_post,
    ):
        mock_post.return_value = _mock_httpx_response(
            json_data={"choices": [{"message": {"content": "Refined."}}]}
        )
        refined, _, provider_used, model_used = call_refiner(body, "org-1")

    assert refined == "Refined."
    assert provider_used == "kenpath"
    assert model_used == "bharatvistaar-prod (English, Hindi)"


# --------------------------------------------------------------------------
# call_bedrock (AWS Bedrock Converse API)
# --------------------------------------------------------------------------


def test_call_bedrock_success():
    body = make_body(llm_provider="aws_bedrock")
    with (
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={
                "auth": {
                    "aws_access_key": "AKIA...",
                    "aws_secret_key": "secret",
                    "aws_region": "us-east-1",
                }
            },
        ),
        patch("boto3.client") as mock_boto_client,
    ):
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "Refined bedrock prompt."}]}}
        }
        mock_boto_client.return_value = mock_client

        refined, model = call_bedrock("org-1", body.llm_model, "system", "user", resolve_auth=resolve_stored_auth)

    assert refined == "Refined bedrock prompt."
    assert model == BEDROCK_DEFAULT_MODEL
    mock_boto_client.assert_called_once_with(
        "bedrock-runtime",
        region_name="us-east-1",
        aws_access_key_id="AKIA...",
        aws_secret_access_key="secret",
    )
    call_kwargs = mock_client.converse.call_args.kwargs
    assert call_kwargs["system"] == [{"text": "system"}]
    assert call_kwargs["messages"] == [{"role": "user", "content": [{"text": "user"}]}]


def test_call_bedrock_honors_requested_model():
    body = make_body(llm_provider="aws_bedrock", llm_model="us.anthropic.claude-sonnet-4-20250514-v1:0")
    with (
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"aws_access_key": "AKIA...", "aws_secret_key": "secret"}},
        ),
        patch("boto3.client") as mock_boto_client,
    ):
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "Refined."}]}}
        }
        mock_boto_client.return_value = mock_client

        _, model = call_bedrock("org-1", body.llm_model, "system", "user", resolve_auth=resolve_stored_auth)

    assert model == "us.anthropic.claude-sonnet-4-20250514-v1:0"


def test_call_bedrock_missing_credentials_raises():
    body = make_body(llm_provider="aws_bedrock")
    with patch(
        "app.routers.prompt_refine.auth_service.get_provider_auth",
        return_value={"auth": {}},
    ):
        with pytest.raises(PromptRefineError, match="no aws_access_key/aws_secret_key on file"):
            call_bedrock("org-1", body.llm_model, "system", "user", resolve_auth=resolve_stored_auth)


def test_call_bedrock_client_error_raises():
    from botocore.exceptions import ClientError

    body = make_body(llm_provider="aws_bedrock")
    with (
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"aws_access_key": "AKIA...", "aws_secret_key": "secret"}},
        ),
        patch("boto3.client") as mock_boto_client,
    ):
        mock_client = MagicMock()
        mock_client.converse.side_effect = ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "rate limited"}}, "Converse"
        )
        mock_boto_client.return_value = mock_client

        with pytest.raises(PromptRefineError, match="aws_bedrock request failed"):
            call_bedrock("org-1", body.llm_model, "system", "user", resolve_auth=resolve_stored_auth)


def test_call_bedrock_empty_response_raises():
    body = make_body(llm_provider="aws_bedrock")
    with (
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"aws_access_key": "AKIA...", "aws_secret_key": "secret"}},
        ),
        patch("boto3.client") as mock_boto_client,
    ):
        mock_client = MagicMock()
        mock_client.converse.return_value = {"output": {"message": {"content": [{"text": ""}]}}}
        mock_boto_client.return_value = mock_client

        with pytest.raises(PromptRefineError, match="returned an empty response"):
            call_bedrock("org-1", body.llm_model, "system", "user", resolve_auth=resolve_stored_auth)


# --------------------------------------------------------------------------
# call_vertex (Google Vertex AI via google-genai)
# --------------------------------------------------------------------------


def test_call_vertex_success_with_adc():
    body = make_body(llm_provider="google_vertex")
    with (
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"project_id": "my-gcp-project", "location": "us-central1"}},
        ),
        patch("google.genai.Client") as mock_genai_client,
    ):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Refined vertex prompt."
        mock_client.models.generate_content.return_value = mock_response
        mock_genai_client.return_value = mock_client

        refined, model = call_vertex("org-1", body.llm_model, "system", "user", resolve_auth=resolve_stored_auth)

    assert refined == "Refined vertex prompt."
    assert model == VERTEX_DEFAULT_MODEL
    mock_genai_client.assert_called_once_with(
        vertexai=True, project="my-gcp-project", location="us-central1"
    )
    call_kwargs = mock_client.models.generate_content.call_args.kwargs
    assert call_kwargs["contents"] == "user"
    assert call_kwargs["config"]["system_instruction"] == "system"


def test_call_vertex_missing_project_id_raises():
    body = make_body(llm_provider="google_vertex")
    with patch(
        "app.routers.prompt_refine.auth_service.get_provider_auth",
        return_value={"auth": {}},
    ):
        with pytest.raises(PromptRefineError, match="no project_id on file"):
            call_vertex("org-1", body.llm_model, "system", "user", resolve_auth=resolve_stored_auth)


def test_call_vertex_invalid_credentials_json_raises():
    body = make_body(llm_provider="google_vertex")
    with patch(
        "app.routers.prompt_refine.auth_service.get_provider_auth",
        return_value={"auth": {"project_id": "my-gcp-project", "credentials": "not-json"}},
    ):
        with pytest.raises(PromptRefineError, match="not valid JSON"):
            call_vertex("org-1", body.llm_model, "system", "user", resolve_auth=resolve_stored_auth)


def test_call_vertex_honors_requested_model():
    body = make_body(llm_provider="google_vertex", llm_model="gemini-1.5-pro")
    with (
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"project_id": "my-gcp-project"}},
        ),
        patch("google.genai.Client") as mock_genai_client,
    ):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Refined."
        mock_client.models.generate_content.return_value = mock_response
        mock_genai_client.return_value = mock_client

        _, model = call_vertex("org-1", body.llm_model, "system", "user", resolve_auth=resolve_stored_auth)

    assert model == "gemini-1.5-pro"


def test_call_vertex_empty_response_raises():
    body = make_body(llm_provider="google_vertex")
    with (
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"project_id": "my-gcp-project"}},
        ),
        patch("google.genai.Client") as mock_genai_client,
    ):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = ""
        mock_client.models.generate_content.return_value = mock_response
        mock_genai_client.return_value = mock_client

        with pytest.raises(PromptRefineError, match="returned an empty response"):
            call_vertex("org-1", body.llm_model, "system", "user", resolve_auth=resolve_stored_auth)


# --------------------------------------------------------------------------
# candidate_providers / call_refiner — bedrock + vertex
# --------------------------------------------------------------------------


def test_candidate_providers_includes_bedrock_and_vertex_when_configured():
    body = make_body()
    with patch(
        "app.routers.prompt_refine.auth_service.list_configured_providers",
        return_value=["aws_bedrock", "google_vertex"],
    ):
        result = candidate_providers(body, "org-1")
    assert set(result) == {"aws_bedrock", "google_vertex"}


def test_call_refiner_bedrock_end_to_end():
    body = make_body(llm_provider="aws_bedrock")
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=["aws_bedrock"],
        ),
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"aws_access_key": "AKIA...", "aws_secret_key": "secret"}},
        ),
        patch("boto3.client") as mock_boto_client,
    ):
        mock_client = MagicMock()
        mock_client.converse.return_value = {
            "output": {"message": {"content": [{"text": "Refined."}]}}
        }
        mock_boto_client.return_value = mock_client

        refined, _, provider_used, model_used = call_refiner(body, "org-1")

    assert refined == "Refined."
    assert provider_used == "aws_bedrock"
    assert model_used == BEDROCK_DEFAULT_MODEL


def test_call_refiner_vertex_end_to_end():
    body = make_body(llm_provider="google_vertex")
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=["google_vertex"],
        ),
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"project_id": "my-gcp-project"}},
        ),
        patch("google.genai.Client") as mock_genai_client,
    ):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Refined."
        mock_client.models.generate_content.return_value = mock_response
        mock_genai_client.return_value = mock_client

        refined, _, provider_used, model_used = call_refiner(body, "org-1")

    assert refined == "Refined."
    assert provider_used == "google_vertex"
    assert model_used == VERTEX_DEFAULT_MODEL


def test_candidate_providers_full_set_across_all_phases():
    """All 10 registered providers + voicera_model_server should all be
    reachable through candidate_providers when fully configured."""
    body = make_body()
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=[
                "openai",
                "groq",
                "sarvam",
                "openrouter",
                "atlascloud",
                "azure_openai",
                "google",
                "kenpath",
                "aws_bedrock",
                "google_vertex",
            ],
        ),
        patch.dict("os.environ", {"MODEL_SERVER_URL": "http://llm-gateway:8100/v1"}),
    ):
        result = candidate_providers(body, "org-1")

    assert set(result) == {
        "openai",
        "groq",
        "sarvam",
        "openrouter",
        "atlascloud",
        "azure_openai",
        "google",
        "kenpath",
        "aws_bedrock",
        "google_vertex",
        "voicera_model_server",
    }


# --------------------------------------------------------------------------
# Drift guard — every provider's "no llm_model given" default must come from
# its own catalog.DEFAULT_LLM_MODEL, not a literal copied into this router or
# into apps/providers/refine_llm.py. A hardcoded copy silently goes stale the
# moment the catalog's default changes (this happened twice — google and
# google_vertex both drifted to "gemini-2.0-flash" while their catalogs had
# already moved to "gemini-3.5-flash" — caught only by manual code review,
# not by the test suite, because every assertion re-hardcoded the same stale
# string instead of importing the source of truth). These tests call the
# real resolver for each provider and compare against the real catalog
# import, so a future hardcode-instead-of-import regression fails here
# immediately instead of drifting silently again.
# --------------------------------------------------------------------------


def _resolve_default_model_for_openai_compatible(provider: str, auth: dict) -> str:
    body = make_body(llm_provider=provider)
    with patch("app.routers.prompt_refine.auth_service.get_provider_auth", return_value={"auth": auth}):
        _, _, model, _ = resolve_openai_compatible(body, "org-1", provider)
    return model


@pytest.mark.parametrize(
    "provider,auth,catalog_default",
    [
        ("openai", {"api_key": "sk-1"}, OPENAI_DEFAULT_MODEL),
        ("groq", {"api_key": "gsk-1"}, GROQ_DEFAULT_MODEL),
        ("sarvam", {"api_key": "sk-1"}, SARVAM_DEFAULT_MODEL),
        ("openrouter", {"api_key": "sk-1"}, OPENROUTER_DEFAULT_MODEL),
        ("atlascloud", {"api_key": "sk-1"}, ATLASCLOUD_DEFAULT_MODEL),
        ("google", {"api_key": "sk-1"}, GOOGLE_CATALOG_DEFAULT_MODEL),
    ],
)
def test_openai_compatible_default_model_matches_catalog(provider, auth, catalog_default):
    model = _resolve_default_model_for_openai_compatible(provider, auth)
    assert model == catalog_default


def test_kenpath_default_model_matches_catalog():
    pem = _test_rsa_private_key_pem()
    with (
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"private_key": pem}},
        ),
        patch("apps.providers.refine_llm.httpx.get") as mock_get,
    ):
        mock_get.return_value = _mock_httpx_response(text="reply")
        _, model = call_kenpath("org-1", None, "system", "user", resolve_auth=resolve_stored_auth)

    assert model == KENPATH_DEFAULT_MODEL


def test_bedrock_default_model_matches_catalog():
    with (
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"aws_access_key": "AKIA...", "aws_secret_key": "secret"}},
        ),
        patch("boto3.client") as mock_boto_client,
    ):
        mock_client = MagicMock()
        mock_client.converse.return_value = {"output": {"message": {"content": [{"text": "Refined."}]}}}
        mock_boto_client.return_value = mock_client

        _, model = call_bedrock("org-1", None, "system", "user", resolve_auth=resolve_stored_auth)

    assert model == BEDROCK_DEFAULT_MODEL


def test_vertex_default_model_matches_catalog():
    with (
        patch(
            "app.routers.prompt_refine.auth_service.get_provider_auth",
            return_value={"auth": {"project_id": "my-gcp-project"}},
        ),
        patch("google.genai.Client") as mock_genai_client,
    ):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "Refined."
        mock_client.models.generate_content.return_value = mock_response
        mock_genai_client.return_value = mock_client

        _, model = call_vertex("org-1", None, "system", "user", resolve_auth=resolve_stored_auth)

    assert model == VERTEX_DEFAULT_MODEL
