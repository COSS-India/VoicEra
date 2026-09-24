"""History mode: agent choice vs endpoint default, and the trim it produces."""

from __future__ import annotations

import pytest

from apps.providers.cloud.openai_compatible.config import OpenAICompatibleLLMConfig
from apps.providers.cloud.openai_compatible.history import (
    drop_system_prompt,
    trim_to_current_turn,
)
from apps.providers.cloud.openai_compatible.service import create_llm
from apps.providers.schema import _auth_field_names, provider_settings
from apps.providers.base import Kind

_SYSTEM = {"role": "system", "content": "You are a helpful agent."}


def _config(**overrides) -> OpenAICompatibleLLMConfig:
    return OpenAICompatibleLLMConfig(
        model="Qwen/Qwen3-8B-Instruct",
        base_url="http://vllm.internal:8000/v1",
        api_key="sk-local",
        **overrides,
    )


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_agent_inherits_the_endpoint_default():
    assert _config(endpoint_history_mode="current_turn").effective_history_mode == "current_turn"
    assert _config(endpoint_history_mode="full").effective_history_mode == "full"


@pytest.mark.parametrize("agent_mode", ["full", "current_turn"])
@pytest.mark.parametrize("endpoint_mode", ["full", "current_turn"])
def test_an_explicit_agent_choice_beats_the_endpoint(agent_mode, endpoint_mode):
    cfg = _config(history_mode=agent_mode, endpoint_history_mode=endpoint_mode)
    assert cfg.effective_history_mode == agent_mode


def test_defaults_match_the_behaviour_before_the_setting_existed():
    cfg = _config()
    assert cfg.history_mode == "inherit"
    assert cfg.effective_history_mode == "full"


def test_the_agent_inherits_the_endpoints_system_prompt_mode():
    assert _config(endpoint_system_prompt_mode="omit").effective_system_prompt_mode == "omit"
    assert _config().effective_system_prompt_mode == "send"
    assert (
        _config(
            system_prompt_mode="send", endpoint_system_prompt_mode="omit"
        ).effective_system_prompt_mode
        == "send"
    )


def test_the_two_modes_are_independent():
    """An endpoint can want the whole conversation and still build its prompt."""
    cfg = _config(endpoint_history_mode="full", endpoint_system_prompt_mode="omit")
    assert cfg.effective_history_mode == "full"
    assert cfg.effective_system_prompt_mode == "omit"


def test_the_endpoint_defaults_are_not_agent_form_fields():
    """They ride the Auth layer, so they are endpoint-owned end to end."""
    auth_fields = _auth_field_names(OpenAICompatibleLLMConfig)
    assert "endpoint_history_mode" in auth_fields
    assert "endpoint_system_prompt_mode" in auth_fields
    fields = provider_settings(Kind.LLM, "openai_compatible")["fields"]
    assert "endpoint_history_mode" not in fields
    assert "endpoint_system_prompt_mode" not in fields
    assert fields["history_mode"]["examples"] == ["inherit", "full", "current_turn"]
    assert fields["system_prompt_mode"]["examples"] == ["inherit", "send", "omit"]
    # The wire values are not readable on their own, so the form gets labels.
    assert fields["history_mode"]["option_labels"] == {
        "inherit": "Inherit from endpoint",
        "full": "Full conversation",
        "current_turn": "Current turn only",
    }
    assert fields["system_prompt_mode"]["option_labels"] == {
        "inherit": "Inherit from endpoint",
        "send": "Send the system prompt",
        "omit": "Endpoint builds its own",
    }


# ---------------------------------------------------------------------------
# Trim
# ---------------------------------------------------------------------------


def test_earlier_turns_are_dropped_and_the_system_prompt_stays():
    messages = [
        _SYSTEM,
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "second"},
    ]
    assert trim_to_current_turn(messages) == [_SYSTEM, {"role": "user", "content": "second"}]


def test_a_tool_round_trip_is_kept_whole():
    """An orphan tool message is a 400, so the tail starts at the user turn."""
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


def test_every_preamble_message_survives():
    developer = {"role": "developer", "content": "Answer in Hindi."}
    messages = [
        _SYSTEM,
        developer,
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "second"},
    ]
    trimmed = trim_to_current_turn(messages)
    assert trimmed[:2] == [_SYSTEM, developer]
    assert trimmed[2:] == [{"role": "user", "content": "second"}]


def test_a_run_with_nothing_said_yet_is_left_alone():
    messages = [_SYSTEM, {"role": "assistant", "content": "Hello!"}]
    assert trim_to_current_turn(messages) == messages
    assert trim_to_current_turn([]) == []


def _request_messages(cfg: OpenAICompatibleLLMConfig, messages: list[dict]) -> list[dict]:
    """Messages as the service would actually put them on the wire."""
    service = create_llm(cfg)
    params = service.build_chat_completion_params({"messages": list(messages)})
    return params["messages"]


def test_the_client_contract_is_one_bare_user_message():
    """Both modes together: exactly the caller's newest utterance, nothing else."""
    history = [
        _SYSTEM,
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "second"},
    ]
    cfg = _config(history_mode="current_turn", system_prompt_mode="omit")
    assert _request_messages(cfg, history) == [{"role": "user", "content": "second"}]


def test_omitting_the_prompt_leaves_the_conversation_alone():
    history = [
        _SYSTEM,
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "second"},
    ]
    cfg = _config(system_prompt_mode="omit")
    assert _request_messages(cfg, history) == history[1:]


def test_a_preamble_with_nothing_else_is_sent_rather_than_emptied():
    """An empty messages list is a 400; an ignored system prompt is not."""
    assert drop_system_prompt([_SYSTEM]) == [_SYSTEM]
    assert drop_system_prompt([]) == []


def test_the_service_sends_one_turn_only_when_the_mode_says_so():
    history = [
        _SYSTEM,
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "answer"},
        {"role": "user", "content": "second"},
    ]
    cfg = _config(history_mode="current_turn")
    assert _request_messages(cfg, history) == [
        _SYSTEM,
        {"role": "user", "content": "second"},
    ]
    # The inherited default leaves the request exactly as it was before.
    assert _request_messages(_config(), history) == history


def test_the_trim_does_not_mutate_the_context_messages():
    messages = [
        _SYSTEM,
        {"role": "user", "content": "first"},
        {"role": "user", "content": "second"},
    ]
    trim_to_current_turn(messages)
    assert len(messages) == 3


# ---------------------------------------------------------------------------
# Caller phone
# ---------------------------------------------------------------------------


def _request_params(cfg: OpenAICompatibleLLMConfig) -> dict:
    return create_llm(cfg).build_chat_completion_params({"messages": [_SYSTEM]})


def test_no_metadata_unless_the_endpoint_asks_for_it():
    params = _request_params(_config(caller_phone="919900112233"))
    assert "metadata" not in params


def test_the_caller_phone_rides_every_request_as_metadata():
    cfg = _config(endpoint_send_caller_phone=True, caller_phone="919900112233")
    assert _request_params(cfg)["metadata"] == {"caller_phone": "919900112233"}
    # The shaped service builds its body the same way.
    cfg = _config(
        endpoint_send_caller_phone=True,
        caller_phone="919900112233",
        history_mode="current_turn",
    )
    assert _request_params(cfg)["metadata"] == {"caller_phone": "919900112233"}


def test_a_call_with_no_number_fails_at_setup():
    with pytest.raises(ValueError, match="phone number"):
        create_llm(_config(endpoint_send_caller_phone=True))


def test_the_caller_phone_fields_are_not_agent_form_fields():
    auth_fields = _auth_field_names(OpenAICompatibleLLMConfig)
    assert {"endpoint_send_caller_phone", "caller_phone"} <= auth_fields
    fields = provider_settings(Kind.LLM, "openai_compatible")["fields"]
    assert "endpoint_send_caller_phone" not in fields
    assert "caller_phone" not in fields
