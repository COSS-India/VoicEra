"""Unit tests for the two bugs fixed in one_shot_llm.py:
1. Kenpath vistaar/voice_bhili refuses instead of silently mistranslating
   with hardcoded source_lang=target_lang="mr".
2. call_via_openai_compatible_provider uses registry.api_key() (which
   raises on an empty rotation list) instead of a duplicate that silently
   returned None.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from apps.providers.one_shot_llm import (
    OneShotLLMError,
    call_first_available,
    call_kenpath,
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
        "apps.providers.one_shot_llm.first_available_provider", return_value="kenpath"
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
        "apps.providers.one_shot_llm.first_available_provider",
        return_value="voicera_model_server",
    ), patch(
        "apps.providers.one_shot_llm.call_local_model_server", return_value="translated"
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
