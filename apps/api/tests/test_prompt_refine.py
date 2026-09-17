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
    infer_mode,
    require_active_org,
    resolve_api_key,
    resolve_openai_compatible,
    resolve_self_hosted,
    resolve_stored_auth,
    resolve_voicera_model_server,
    summarize_changes,
    validate_refined_prompt,
)
from app.utils.ssrf_guard import reject_metadata_endpoint
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
# reject_metadata_endpoint (SSRF guard for self-hosted llm_base_url)
# --------------------------------------------------------------------------


def test_reject_metadata_endpoint_blocks_aws_gcp_azure_imds_ip():
    with pytest.raises(ValueError, match="metadata"):
        reject_metadata_endpoint("http://169.254.169.254/latest/meta-data/")


def test_reject_metadata_endpoint_blocks_decimal_encoded_ip():
    """2852039166 is the decimal encoding of 169.254.169.254 — a naive
    string-only blocklist would miss this."""
    with pytest.raises(ValueError, match="metadata"):
        reject_metadata_endpoint("http://2852039166/")


def test_reject_metadata_endpoint_blocks_hostname():
    with pytest.raises(ValueError, match="metadata"):
        reject_metadata_endpoint("http://metadata.google.internal/computeMetadata/v1/")


def test_reject_metadata_endpoint_allows_localhost():
    reject_metadata_endpoint("http://localhost:11434/v1")


def test_reject_metadata_endpoint_allows_private_ip():
    reject_metadata_endpoint("http://10.0.0.5:8003/v1")


def test_reject_metadata_endpoint_allows_public_looking_host():
    with patch(
        "app.utils.ssrf_guard.socket.getaddrinfo",
        return_value=[(None, None, None, None, ("203.0.113.10", 0))],
    ):
        reject_metadata_endpoint("https://my-llm-server.example.com/v1")


def test_reject_metadata_endpoint_unresolvable_host_raises():
    with pytest.raises(ValueError, match="Could not resolve"):
        reject_metadata_endpoint("http://this-host-does-not-exist.invalid/v1")


def test_reject_metadata_endpoint_no_hostname_raises():
    with pytest.raises(ValueError, match="Could not parse"):
        reject_metadata_endpoint("not-a-url")


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
    assert model == "gemini-2.0-flash"
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
# resolve_self_hosted
# --------------------------------------------------------------------------


def test_resolve_self_hosted_uses_request_supplied_url():
    body = make_body(
        llm_provider="self_hosted",
        llm_model="llama3:8b",
        llm_base_url="http://localhost:11434/v1",
    )
    api_key, base_url, model = resolve_self_hosted(body)

    assert api_key is None
    assert base_url == "http://localhost:11434/v1"
    assert model == "llama3:8b"


def test_resolve_self_hosted_requires_base_url():
    body = make_body(llm_provider="self_hosted", llm_model="llama3:8b")
    with pytest.raises(PromptRefineError, match="requires llm_base_url"):
        resolve_self_hosted(body)


def test_resolve_self_hosted_requires_model():
    body = make_body(llm_provider="self_hosted", llm_base_url="http://localhost:11434/v1")
    with pytest.raises(PromptRefineError, match="requires llm_model"):
        resolve_self_hosted(body)


def test_resolve_self_hosted_rejects_metadata_url():
    body = make_body(
        llm_provider="self_hosted",
        llm_model="llama3:8b",
        llm_base_url="http://169.254.169.254/",
    )
    with pytest.raises(PromptRefineError, match="metadata"):
        resolve_self_hosted(body)


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


def test_candidate_providers_includes_self_hosted_when_base_url_given():
    body = make_body(llm_base_url="http://localhost:11434/v1")
    with patch(
        "app.routers.prompt_refine.auth_service.list_configured_providers",
        return_value=["openai"],
    ):
        result = candidate_providers(body, "org-1")
    assert "self_hosted" in result


def test_candidate_providers_excludes_self_hosted_without_base_url():
    body = make_body()
    with patch(
        "app.routers.prompt_refine.auth_service.list_configured_providers",
        return_value=["openai"],
    ):
        result = candidate_providers(body, "org-1")
    assert "self_hosted" not in result


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


def test_call_refiner_uses_self_hosted_end_to_end():
    body = make_body(
        llm_provider="self_hosted",
        llm_model="llama3:8b",
        llm_base_url="http://localhost:11434/v1",
    )
    with (
        patch(
            "app.routers.prompt_refine.auth_service.list_configured_providers",
            return_value=[],
        ),
        patch("app.routers.prompt_refine.OpenAI") as mock_openai,
    ):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = _mock_completion("Refined.")
        mock_openai.return_value = mock_client

        refined, _, provider_used, model_used = call_refiner(body, "org-1")

    assert refined == "Refined."
    assert provider_used == "self_hosted"
    assert model_used == "llama3:8b"


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

    from apps.providers.adapters.kenpath.catalog import DEFAULT_LLM_MODEL as KENPATH_DEFAULT_MODEL

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
    assert model == "us.amazon.nova-pro-v1:0"
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
    assert model == "gemini-2.0-flash"
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
    assert model_used == "us.amazon.nova-pro-v1:0"


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
    assert model_used == "gemini-2.0-flash"


def test_candidate_providers_full_set_across_all_phases():
    """All 10 registered providers + voicera_model_server + self_hosted should
    all be reachable through candidate_providers when fully configured."""
    body = make_body(llm_base_url="http://localhost:11434/v1", llm_model="llama3:8b")
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
        "self_hosted",
    }
