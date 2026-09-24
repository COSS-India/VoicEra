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
