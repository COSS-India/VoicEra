"""Unit tests for prompt custom-variable substitution."""

from __future__ import annotations

from apps.runtime.routes.telephony import _websocket_url_for_agent
from apps.runtime.services.pipecat.audio import (
    prompts,
    resolve_custom_variables,
    substitute_variables,
)


def test_substitute_variables_single_replacement() -> None:
    text = "Hello {{customer_name}}, welcome."
    assert substitute_variables(text, {"customer_name": "Jane"}) == "Hello Jane, welcome."


def test_substitute_variables_multiple_replacements() -> None:
    text = "{{greeting}} {{customer_name}} ({{account_id}})"
    variables = {
        "greeting": "Hi",
        "customer_name": "Jane",
        "account_id": "ACC-1",
    }
    assert substitute_variables(text, variables) == "Hi Jane (ACC-1)"


def test_substitute_variables_missing_key_becomes_empty() -> None:
    assert substitute_variables("Hi {{name}}", {}) == "Hi "
    assert substitute_variables("{{a}} and {{b}}", {"a": "x"}) == "x and "


def test_substitute_variables_coerces_non_string_values() -> None:
    assert substitute_variables("Count: {{n}}", {"n": 42}) == "Count: 42"


def test_resolve_custom_variables_merges_call_over_agent() -> None:
    agent = {
        "config": {
            "custom_variables": {
                "customer_name": "there",
                "account_id": "unknown",
            }
        }
    }
    call_log = {"custom_variables": {"customer_name": "Jane Doe"}}
    assert resolve_custom_variables(agent, call_log) == {
        "customer_name": "Jane Doe",
        "account_id": "unknown",
    }


def test_resolve_custom_variables_agent_defaults_only() -> None:
    agent = {"config": {"custom_variables": {"tier": "gold"}}}
    assert resolve_custom_variables(agent, None) == {"tier": "gold"}
    assert resolve_custom_variables(agent, {}) == {"tier": "gold"}


def test_resolve_custom_variables_ignores_invalid_shapes() -> None:
    agent = {"config": {"custom_variables": "bad"}}
    call_log = {"custom_variables": ["not", "a", "dict"]}
    assert resolve_custom_variables(agent, call_log) == {}


def test_prompts_applies_substitution_when_variables_provided() -> None:
    agent = {
        "config": {
            "prompts": {
                "system_prompt": "Help {{customer_name}} with {{account_id}}.",
                "greeting_message": "Hi {{customer_name}}!",
            },
            "custom_variables": {
                "customer_name": "there",
                "account_id": "unknown",
            },
        }
    }
    call_log = {"custom_variables": {"customer_name": "Jane Doe"}}
    variables = resolve_custom_variables(agent, call_log)
    system_prompt, greeting = prompts(agent, custom_variables=variables)
    assert system_prompt == "Help Jane Doe with unknown."
    assert greeting == "Hi Jane Doe!"


def test_prompts_without_variables_leaves_placeholders() -> None:
    agent = {
        "config": {
            "prompts": {
                "system_prompt": "Help {{customer_name}}.",
                "greeting_message": "Hi {{customer_name}}!",
            }
        }
    }
    system_prompt, greeting = prompts(agent)
    assert system_prompt == "Help {{customer_name}}."
    assert greeting == "Hi {{customer_name}}!"


def test_websocket_url_includes_call_id_query_param(monkeypatch) -> None:
    monkeypatch.setenv("VOICE_SERVER_BASE_URL", "https://voice.example.com")
    url = _websocket_url_for_agent("org-1", "agent-1", "call-abc-123")
    assert url == "wss://voice.example.com/agent/org-1/agent-1?call_id=call-abc-123"


def test_websocket_url_omits_query_when_no_call_id(monkeypatch) -> None:
    monkeypatch.setenv("VOICE_SERVER_BASE_URL", "https://voice.example.com")
    url = _websocket_url_for_agent("org-1", "agent-1")
    assert url == "wss://voice.example.com/agent/org-1/agent-1"
