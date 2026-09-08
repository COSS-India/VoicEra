"""Audio encoding utilities for the Pipecat pipeline."""

from __future__ import annotations

import io
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
