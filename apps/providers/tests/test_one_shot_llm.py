"""Unit tests for the two bugs fixed in one_shot_llm.py:
1. Kenpath vistaar/voice_bhili refuses instead of silently mistranslating
   with hardcoded source_lang=target_lang="mr".
2. call_via_openai_compatible_provider uses registry.api_key() (which
   raises on an empty rotation list) instead of a duplicate that silently
   returned None.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from apps.providers.adapters.kenpath.catalog import BHARAT_VISTAAR_PROD_MODEL
from apps.providers.one_shot_llm import (
    OneShotLLMError,
    call_first_available,
    call_kenpath,
    call_local_model_server,
    call_openai_compatible,
    call_via_openai_compatible_provider,
)

ORG_ID = "org-1"


def test_kenpath_vistaar_refuses_instead_of_mistranslating():
    """Vistaar/voice_bhili has no prompt concept — it's a fixed source/target
    language API. It must refuse a one-shot completion request rather than
    silently sending source_lang=target_lang="mr" regardless of what the
    caller actually wants translated."""

    def resolve_auth(org_id: str, provider: str) -> dict:
        return {"private_key": "fake-private-key"}

    with pytest.raises(OneShotLLMError, match="does not support one-shot completions"):
        call_kenpath(
            ORG_ID,
            None,  # requested_model=None resolves to the vistaar default model
            "system prompt",
            "user prompt",
            resolve_auth=resolve_auth,
        )


def test_kenpath_bharatvistaar_malformed_json_raises_one_shot_llm_error():
    """response.json() must be inside the same try/except as the request
    itself — otherwise a malformed/truncated 200 body raises
    json.JSONDecodeError (a ValueError, not httpx.HTTPError), which escapes
    uncaught past call_first_available's `except OneShotLLMError` and kills
    the whole provider-fallback loop instead of advancing to the next
    candidate."""

    def resolve_auth(org_id: str, provider: str) -> dict:
        return {"bharat_prod_private_key": "fake-private-key"}

    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")

    with patch("apps.providers.one_shot_llm.httpx.post", return_value=mock_response), patch(
        "apps.providers.one_shot_llm.kenpath_generate_jwt", return_value="fake-jwt"
    ):
        with pytest.raises(OneShotLLMError, match="non-JSON response"):
            call_kenpath(
                ORG_ID,
                BHARAT_VISTAAR_PROD_MODEL,
                "system prompt",
                "user prompt",
                resolve_auth=resolve_auth,
            )


def test_openai_compatible_provider_uses_first_rotation_key():
    def resolve_auth(org_id: str, provider: str) -> dict:
        return {"api_key": ["key-1", "key-2"]}

    with patch(
        "apps.providers.one_shot_llm.call_openai_compatible", return_value="translated text"
    ) as mock_call:
        result, model = call_via_openai_compatible_provider(
            ORG_ID, "groq", "system", "user", resolve_auth=resolve_auth
        )

    assert mock_call.call_args.args[0] == "key-1"
    assert result == "translated text"


def test_openai_compatible_provider_empty_key_list_raises_clean_error():
    """registry.api_key([]) raises ValueError on an empty rotation list;
    that must surface as the same clean 'no api_key on file' error as a
    missing key, not an unhandled ValueError."""

    def resolve_auth(org_id: str, provider: str) -> dict:
        return {"api_key": []}

    with pytest.raises(OneShotLLMError, match="no api_key on file"):
        call_via_openai_compatible_provider(
            ORG_ID, "groq", "system", "user", resolve_auth=resolve_auth
        )


def test_first_available_forwards_max_tokens_to_kenpath():
    """call_first_available must thread max_tokens through to every provider
    branch it dispatches to, including kenpath — a caller like
    translation_service passes max_tokens to bound completion size, and a
    dropped kwarg on one branch silently disables that cap only for orgs on
    that provider, reopening the silent-truncation bug this plumbing exists
    to close."""

    def resolve_auth(org_id: str, provider: str) -> dict:
        return {}

    with patch(
        "apps.providers.one_shot_llm.available_providers", return_value=["kenpath"]
    ), patch(
        "apps.providers.one_shot_llm.call_kenpath", return_value=("translated", "some-model")
    ) as mock_call:
        call_first_available(
            ORG_ID,
            "system",
            "user",
            resolve_auth=resolve_auth,
            list_configured_providers=lambda org_id: ["kenpath"],
            max_tokens=12_000,
        )

    assert mock_call.call_args.kwargs["max_tokens"] == 12_000


def test_first_available_forwards_max_tokens_to_local_model_server():
    def resolve_auth(org_id: str, provider: str) -> dict:
        return {}

    with patch(
        "apps.providers.one_shot_llm.available_providers",
        return_value=["voicera_model_server"],
    ), patch(
        "apps.providers.one_shot_llm.call_local_model_server",
        return_value=("translated", "qwen3.5-4b"),
    ) as mock_call:
        call_first_available(
            ORG_ID,
            "system",
            "user",
            resolve_auth=resolve_auth,
            list_configured_providers=lambda org_id: [],
            max_tokens=12_000,
        )

    assert mock_call.call_args.kwargs["max_tokens"] == 12_000


def _mock_openai_client(content: str, finish_reason: str):
    completion = MagicMock()
    message = MagicMock(content=content)
    completion.choices = [MagicMock(message=message, finish_reason=finish_reason)]
    client = MagicMock()
    client.chat.completions.create.return_value = completion
    return client


def test_call_openai_compatible_raises_on_truncated_output():
    """A completion cut off by the model's own max_tokens cap
    (finish_reason=length) must surface as an explicit truncation error, not
    silently return the partial text for translation_service's line-count
    check to misdiagnose as 'changed the transcript's line structure'."""
    with patch(
        "apps.providers.one_shot_llm.OpenAI",
        return_value=_mock_openai_client("[00:01] agent: partial tr", "length"),
    ):
        with pytest.raises(OneShotLLMError, match="truncated"):
            call_openai_compatible(
                "key", None, "some-model", [{"role": "user", "content": "hi"}], max_tokens=10
            )


def test_call_openai_compatible_accepts_complete_output():
    with patch(
        "apps.providers.one_shot_llm.OpenAI",
        return_value=_mock_openai_client("[00:01] agent: hi", "stop"),
    ):
        result = call_openai_compatible(
            "key", None, "some-model", [{"role": "user", "content": "hi"}], max_tokens=10
        )
    assert result == "[00:01] agent: hi"


def test_call_local_model_server_rejects_request_exceeding_context_window():
    """qwen3.5-4b's serving context is capped at 8192 tokens
    (model-server/models.yaml, VLLM_MAX_MODEL_LEN). A large transcript plus
    its requested max_tokens can exceed that outright — this must fail with
    an actionable error instead of a generic 502 from vLLM."""
    huge_user_text = "x" * 20_000
    with patch.dict("os.environ", {"MODEL_SERVER_URL": "http://model-server:8000"}), patch(
        "apps.providers.one_shot_llm.deployed_llm_model_ids", return_value=frozenset({"qwen3.5-4b"})
    ):
        with pytest.raises(OneShotLLMError, match="context window"):
            call_local_model_server("system prompt", huge_user_text, max_tokens=12_000)


def test_call_local_model_server_allows_request_within_context_window():
    with patch.dict("os.environ", {"MODEL_SERVER_URL": "http://model-server:8000"}), patch(
        "apps.providers.one_shot_llm.deployed_llm_model_ids", return_value=frozenset({"qwen3.5-4b"})
    ), patch(
        "apps.providers.one_shot_llm.call_openai_compatible", return_value="translated"
    ) as mock_call:
        result, model = call_local_model_server("short system", "short user", max_tokens=200)
    assert result == "translated"
    assert model == "qwen3.5-4b"
    assert mock_call.call_args.kwargs["max_tokens"] == 200


def test_call_local_model_server_uses_deployed_model_id_from_model_server():
    """model-server's actually-deployed LLM slot is configurable (LLM_MODEL
    env var on model-server's own side) — this must ask model-server's own
    /models report rather than hardcoding "qwen3.5-4b", or any deployment
    with a different slot name 404s on every call."""
    with patch.dict("os.environ", {"MODEL_SERVER_URL": "http://model-server:8000"}), patch(
        "apps.providers.one_shot_llm.deployed_llm_model_ids", return_value=frozenset({"custom-slot-name"})
    ), patch(
        "apps.providers.one_shot_llm.call_openai_compatible", return_value="translated"
    ) as mock_call:
        result, model = call_local_model_server("short system", "short user", max_tokens=200)
    assert model == "custom-slot-name"
    assert mock_call.call_args.args[2] == "custom-slot-name"


def test_call_local_model_server_raises_when_no_llm_reported_deployed():
    """If model-server's /models reports no deployed LLM (unreachable,
    still starting up, or the llm slot isn't enabled), this must fail
    loudly rather than guessing a hardcoded model name — a stale/wrong
    guess would silently 404, reproducing the exact bug this resolution
    logic exists to prevent."""
    with patch.dict("os.environ", {"MODEL_SERVER_URL": "http://model-server:8000"}), patch(
        "apps.providers.one_shot_llm.deployed_llm_model_ids", return_value=frozenset()
    ):
        with pytest.raises(OneShotLLMError, match="no deployed LLM model"):
            call_local_model_server("short system", "short user", max_tokens=200)


def test_call_local_model_server_picks_deterministically_among_multiple_deployed():
    """deployed_llm_model_ids() returns a frozenset (no defined iteration
    order) — picking via next(iter(...)) would be non-deterministic if
    model-server ever momentarily reports more than one deployed LLM
    entry (e.g. mid model swap). sorted()[0] must be used instead."""
    with patch.dict("os.environ", {"MODEL_SERVER_URL": "http://model-server:8000"}), patch(
        "apps.providers.one_shot_llm.deployed_llm_model_ids",
        return_value=frozenset({"z-model", "a-model"}),
    ), patch("apps.providers.one_shot_llm.call_openai_compatible", return_value="translated"):
        _, model = call_local_model_server("short system", "short user", max_tokens=200)
    assert model == "a-model"


def test_call_first_available_falls_back_to_next_provider_on_failure():
    """An org whose only configured provider is Kenpath Vistaar/Voice-Bhili
    (call_kenpath raises for that backend — see
    test_kenpath_vistaar_refuses_instead_of_mistranslating) must still reach
    a reachable self-hosted model-server fallback, instead of failing
    outright because the first candidate in priority order didn't work."""

    def resolve_auth(org_id: str, provider: str) -> dict:
        return {}

    with patch(
        "apps.providers.one_shot_llm.available_providers",
        return_value=["kenpath", "voicera_model_server"],
    ), patch(
        "apps.providers.one_shot_llm.call_kenpath",
        side_effect=OneShotLLMError("vistaar/voice_bhili does not support one-shot completions"),
    ) as mock_kenpath, patch(
        "apps.providers.one_shot_llm.call_local_model_server",
        return_value=("translated", "qwen3.5-4b"),
    ) as mock_local:
        dispatched = call_first_available(
            ORG_ID,
            "system",
            "user",
            resolve_auth=resolve_auth,
            list_configured_providers=lambda org_id: ["kenpath"],
        )

    mock_kenpath.assert_called_once()
    mock_local.assert_called_once()
    assert dispatched == ("voicera_model_server", "qwen3.5-4b", "translated")


def test_call_first_available_raises_combined_error_when_all_providers_fail():
    """Every provider's own failure reason must be visible in the raised
    error — not just the last one tried — or a real, fixable problem on a
    higher-priority provider (bad key, misconfig) gets hidden behind an
    unrelated failure from whatever provider happened to be tried last."""

    def resolve_auth(org_id: str, provider: str) -> dict:
        return {}

    with patch(
        "apps.providers.one_shot_llm.available_providers",
        return_value=["kenpath", "voicera_model_server"],
    ), patch(
        "apps.providers.one_shot_llm.call_kenpath", side_effect=OneShotLLMError("kenpath failed")
    ), patch(
        "apps.providers.one_shot_llm.call_local_model_server",
        side_effect=OneShotLLMError("local model server failed"),
    ):
        with pytest.raises(OneShotLLMError, match="kenpath failed") as exc_info:
            call_first_available(
                ORG_ID,
                "system",
                "user",
                resolve_auth=resolve_auth,
                list_configured_providers=lambda org_id: ["kenpath"],
            )

    assert "local model server failed" in str(exc_info.value)
