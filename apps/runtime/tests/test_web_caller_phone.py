"""A browser test call can carry a stand-in caller number (BlueDots needs one)."""

from __future__ import annotations

import pytest

from apps.runtime.services.pipecat.audio import (
    caller_phone,
    resolve_custom_variables,
    web_caller_phone,
)


@pytest.mark.parametrize(
    ("variables", "expected"),
    [
        ({"caller_phone": "+91 99000-00001"}, "919900000001"),
        ({"caller_phone": 919900000001}, "919900000001"),
        ({"caller_phone": ""}, None),
        ({"caller_phone": "n/a"}, None),
        ({"name": "Jane"}, None),
        (None, None),
    ],
)
def test_web_caller_phone_is_the_custom_variable_as_digits(variables, expected, monkeypatch) -> None:
    monkeypatch.delenv("WEB_CALL_CALLER_PHONE", raising=False)
    assert web_caller_phone(variables) == expected


def test_deployment_default_applies_when_no_variable_is_set(monkeypatch) -> None:
    monkeypatch.setenv("WEB_CALL_CALLER_PHONE", "+91 99000-00009")
    assert web_caller_phone({}) == "919900000009"
    assert web_caller_phone(None) == "919900000009"
    assert web_caller_phone({"caller_phone": ""}) == "919900000009"
    # A custom variable still wins.
    assert web_caller_phone({"caller_phone": "919900000001"}) == "919900000001"
    monkeypatch.setenv("WEB_CALL_CALLER_PHONE", "")
    assert web_caller_phone({}) is None


def test_agent_default_and_web_call_override(monkeypatch) -> None:
    monkeypatch.delenv("WEB_CALL_CALLER_PHONE", raising=False)
    agent = {"config": {"custom_variables": {"caller_phone": "919900000001"}}}
    assert web_caller_phone(resolve_custom_variables(agent, None)) == "919900000001"
    call = {"call_type": "web", "custom_variables": {"caller_phone": "919900000002"}}
    assert web_caller_phone(resolve_custom_variables(agent, call)) == "919900000002"


def test_a_phone_call_never_uses_the_stand_in(monkeypatch) -> None:
    monkeypatch.setenv("WEB_CALL_CALLER_PHONE", "919900000009")
    call = {
        "call_type": "inbound",
        "from_number": "",
        "custom_variables": {"caller_phone": "919900000001"},
    }
    assert caller_phone(call) is None

