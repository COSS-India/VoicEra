"""Audio encoding utilities for the Pipecat pipeline."""

from __future__ import annotations

import io
import os
import re
import wave
from typing import Any

_VARIABLE_PATTERN = re.compile(r"\{\{(\w+)\}\}")


def substitute_variables(text: str, variables: dict[str, Any]) -> str:
    """Replace ``{{variable_name}}`` placeholders with string values."""

    def repl(match: re.Match[str]) -> str:
        return str(variables.get(match.group(1), ""))

    return _VARIABLE_PATTERN.sub(repl, text)


def resolve_custom_variables(
    agent: dict[str, Any],
    call_log: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge agent config defaults with per-call overrides (call wins)."""
    config = agent.get("config") or {}
    config_vars = config.get("custom_variables") or {}
    if not isinstance(config_vars, dict):
        config_vars = {}
    call_vars = (call_log or {}).get("custom_variables") or {}
    if not isinstance(call_vars, dict):
        call_vars = {}
    return {**config_vars, **call_vars}


def caller_phone(call_log: dict[str, Any] | None) -> str | None:
    """The remote party's number as digits only, country code first.

    That is ``from_number`` on an inbound call and ``to_number`` on an
    outbound one; a web call, or a number never learned, gives ``None``.
    """
    call_log = call_log or {}
    field = {"inbound": "from_number", "outbound": "to_number"}.get(
        str(call_log.get("call_type") or "")
    )
    if field is None:
        return None
    return re.sub(r"\D", "", str(call_log.get(field) or "")) or None


# Custom variable a browser test call can carry as the caller's number. A
# phone call never reads it: its number is the call's own (``caller_phone``).
TEST_CALLER_PHONE_VARIABLE = "caller_phone"
# Deployment-wide stand-in number for browser calls that set none.
WEB_CALL_CALLER_PHONE_ENV = "WEB_CALL_CALLER_PHONE"


def web_caller_phone(custom_variables: dict[str, Any] | None) -> str | None:
    """A browser test call's stand-in caller number, digits only, or ``None``.

    A web call has no phone number, but an LLM endpoint such as BlueDots' keys
    the caller's profile on one. The ``caller_phone`` custom variable (on the
    agent, or on the web call) wins; otherwise the deployment's
    ``WEB_CALL_CALLER_PHONE`` setting applies to every agent's browser calls.
    """
    for value in (
        (custom_variables or {}).get(TEST_CALLER_PHONE_VARIABLE),
        os.getenv(WEB_CALL_CALLER_PHONE_ENV),
    ):
        digits = re.sub(r"\D", "", str(value or ""))
        if digits:
            return digits
    return None


def prompts(
    agent: dict[str, Any],
    *,
    custom_variables: dict[str, Any] | None = None,
) -> tuple[str, str]:
    config = agent.get("config") or {}
    prompt_config = config.get("prompts") or {}
    system_prompt = str(prompt_config.get("system_prompt") or "").strip()
    greeting = str(prompt_config.get("greeting_message") or "").strip()
    if custom_variables is not None:
        system_prompt = substitute_variables(system_prompt, custom_variables)
        greeting = substitute_variables(greeting, custom_variables)
    return system_prompt, greeting


def wav_bytes(audio: bytes, sample_rate: int, num_channels: int) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(num_channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio)
    return buffer.getvalue()
