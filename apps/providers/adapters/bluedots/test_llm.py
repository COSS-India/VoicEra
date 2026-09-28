"""BlueDots LLM: current-turn trim, caller-phone metadata, catalog wiring."""

from __future__ import annotations

import pytest

from apps.providers.adapters.bluedots.catalog import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    resolve_base_url,
)
from apps.providers.adapters.bluedots.config import BlueDotsLLMConfig
from apps.providers.adapters.bluedots.history import trim_to_current_turn
from apps.providers.adapters.bluedots.service import create_llm
from apps.providers.base import Kind
from apps.providers.schema import _auth_field_names, provider_schemas, provider_settings

_SYSTEM = {"role": "system", "content": "You are a helpful agent."}


def _config(**overrides) -> BlueDotsLLMConfig:
    return BlueDotsLLMConfig(
        api_key="sk-bluedots",
        **overrides,
    )


# ---------------------------------------------------------------------------
# Catalog / schema
# ---------------------------------------------------------------------------


def test_resolve_base_url_prefers_override():
    assert resolve_base_url(None) == DEFAULT_BASE_URL.rstrip("/")
    assert resolve_base_url("  https://custom.example/v1/  ") == "https://custom.example/v1"


def test_bluedots_registered_as_adapter():
    from apps.providers import ProviderType

    schema = provider_schemas(Kind.LLM)["bluedots"]
    assert schema["provider_type"] == ProviderType.ADAPTER
    assert schema["name"] == "BlueDots"
    assert set(schema["secrets"]) == {"api_key", "base_url"}
    assert schema["fields"]["model"]["examples"] == [DEFAULT_MODEL]


def test_agent_form_does_not_expose_auth_endpoint_fields():
    fields = provider_settings(Kind.LLM, "bluedots")["fields"]
    assert "base_url" not in fields
    assert "api_key" not in fields
    assert "caller_phone" not in fields


def test_base_url_and_api_key_are_auth_secrets():
    auth_fields = _auth_field_names(BlueDotsLLMConfig)
    assert {"api_key", "base_url", "caller_phone"} <= auth_fields
    schema = provider_schemas(Kind.LLM)["bluedots"]
    assert schema["fields"]["base_url"]["secret"] is True
    assert schema["fields"]["api_key"]["secret"] is True


# ---------------------------------------------------------------------------
# History trim
# ---------------------------------------------------------------------------


def test_earlier_turns_are_dropped_and_the_system_prompt_stays():
    messages = [
        _SYSTEM,
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "second"},
    ]
    assert trim_to_current_turn(messages) == [
        _SYSTEM,
        {"role": "user", "content": "second"},
    ]


def test_a_tool_round_trip_is_kept_whole():
    call = {
        "role": "assistant",
        "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "end"}}],
    }
    result = {"role": "tool", "tool_call_id": "c1", "content": "{}"}
    messages = [
        _SYSTEM,
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "bye"},
        call,
        result,
    ]
    assert trim_to_current_turn(messages) == [
        _SYSTEM,
        {"role": "user", "content": "bye"},
        call,
        result,
    ]


def test_a_run_with_nothing_said_yet_is_left_alone():
    messages = [_SYSTEM, {"role": "assistant", "content": "Hello!"}]
    assert trim_to_current_turn(messages) == messages
    assert trim_to_current_turn([]) == []


def test_the_trim_does_not_mutate_the_context_messages():
    messages = [
        _SYSTEM,
        {"role": "user", "content": "first"},
        {"role": "user", "content": "second"},
    ]
    trim_to_current_turn(messages)
    assert len(messages) == 3


# ---------------------------------------------------------------------------
# Service wire contract (needs pipecat)
# ---------------------------------------------------------------------------


def _request_params(cfg: BlueDotsLLMConfig, messages: list[dict] | None = None) -> dict:
    pytest.importorskip("pipecat")
    service = create_llm(cfg)
    return service.build_chat_completion_params(
        {"messages": list(messages or [_SYSTEM])}
    )


def test_the_service_sends_current_turn_only():
    history = [
        _SYSTEM,
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "second"},
    ]
    params = _request_params(_config(), history)
    assert params["messages"] == [
        _SYSTEM,
        {"role": "user", "content": "second"},
    ]


def test_the_caller_phone_rides_every_request_as_metadata():
    params = _request_params(_config(caller_phone="919900112233"))
    assert params["metadata"] == {"caller_phone": "919900112233"}


def test_a_call_with_no_number_sends_it_empty():
    params = _request_params(_config())
    assert params["metadata"] == {"caller_phone": ""}


def test_create_llm_uses_catalog_base_url_by_default():
    pytest.importorskip("pipecat")
    service = create_llm(_config())
    assert str(service._client.base_url).rstrip("/") == DEFAULT_BASE_URL.rstrip("/")


def test_create_llm_honours_auth_base_url():
    pytest.importorskip("pipecat")
    service = create_llm(_config(base_url="https://override.example/v1"))
    assert "override.example" in str(service._client.base_url)
