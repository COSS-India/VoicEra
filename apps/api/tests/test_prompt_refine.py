"""Unit + HTTP-mapping tests for the prompt-refine endpoint and its helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from openai import APIConnectionError, APIError

from app.auth import get_current_user
from app.routers import prompt_refine
from app.routers.prompt_refine import (
    PromptRefineError,
    PromptRefineRequest,
    build_context,
    candidate_providers,
    call_refiner,
    infer_mode,
    require_active_org,
    resolve_api_key,
    summarize_changes,
    validate_refined_prompt,
)

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


# --------------------------------------------------------------------------
# validate_refined_prompt
# --------------------------------------------------------------------------


def test_validate_refined_prompt_flags_missing_absolute_rule():
    warnings = validate_refined_prompt("Just a plain prompt with no rule.")
    assert any("factual-value safety rule" in w for w in warnings)


def test_validate_refined_prompt_passes_with_absolute_rule():
    warnings = validate_refined_prompt("Some prompt.\n\nABSOLUTE RULE: never guess.")
    assert not any("factual-value safety rule" in w for w in warnings)


def test_validate_refined_prompt_flags_leaked_secret():
    warnings = validate_refined_prompt("api_key: sk-abc123\n\nABSOLUTE RULE: never guess.")
    assert any("credential or secret" in w for w in warnings)


def test_validate_refined_prompt_clean_has_no_warnings():
    warnings = validate_refined_prompt("A clean prompt.\n\nABSOLUTE RULE: never guess.")
    assert warnings == []


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

        with pytest.raises(PromptRefineError, match="openai request failed"):
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
    assert body["model_used"] == "gpt-4o-mini"
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
    assert "openai request failed" in response.json()["detail"]


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
