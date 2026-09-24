"""OpenAI-compatible LLM configuration.

Every other vendor here talks to one fixed host, so it ships a ``catalog.py``
of that vendor's models and hard-codes the endpoint. This one has neither: the
endpoint, the key, and the model list come from a **provider connection** — an
org-scoped record the operator creates in the dashboard. One organisation can
hold several connections at once (vLLM on a GPU box, Ollama on a laptop, a
hosted gateway), each with its own key.

``base_url`` and ``api_key`` sit on the ``*Auth`` layer, so the existing
machinery already does the right thing with them: the auth catalog renders the
connection form, and ``validate_persisted_model_config`` keeps both out of the
saved agent. The agent stores ``connection_id``; the runtime resolves it and
merges the pair back in just before the pipeline starts.

``endpoint_history_mode`` and ``endpoint_system_prompt_mode`` ride the same
layer for the same reason: they belong to the endpoint, so they are never
stored on an agent and never show up in the agent form. The agent's own
``history_mode`` / ``system_prompt_mode`` default to ``inherit``, and the
``effective_*`` properties pick between the two.

``endpoint_send_caller_phone`` is likewise the connection's, and
``caller_phone`` is per-call context the runtime adds at call setup; both sit
on the Auth layer so neither can be saved on an agent.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ...base import (
    BaseLLMConfig,
    BaseLLMSettings,
    HistoryMode,
    SystemPromptMode,
)

_URL_SCHEMES = ("http://", "https://")


class OpenAICompatibleAuth(BaseModel):
    base_url: str | None = Field(
        default=None,
        description=(
            "Endpoint serving OpenAI's /chat/completions, including any version "
            "path — for example http://models.internal:8100/v1."
        ),
    )
    api_key: str | list[str] | None = Field(
        default=None,
        description=(
            "API key for the endpoint (or a list for rotation). An endpoint that "
            "checks no key still needs a placeholder, because the OpenAI client "
            "refuses to start without one."
        ),
        json_schema_extra={"secret": True},
    )

    endpoint_history_mode: HistoryMode = Field(
        default="full",
        description=(
            "The connection's own history default, applied to every agent that "
            "leaves its history_mode on 'inherit'. Set on the endpoint, not the "
            "agent; the runtime merges it in alongside base_url and api_key."
        ),
    )
    endpoint_system_prompt_mode: SystemPromptMode = Field(
        default="send",
        description=(
            "The connection's own system-prompt default, applied to every "
            "agent that leaves its system_prompt_mode on 'inherit'."
        ),
    )
    endpoint_send_caller_phone: bool = Field(
        default=False,
        description=(
            "Whether the endpoint requires the caller's number as "
            "metadata.caller_phone on every request. Set on the connection."
        ),
    )
    caller_phone: str | None = Field(
        default=None,
        description=(
            "The caller's number for this call, digits only with country code. "
            "Merged in by the runtime per call; never stored on an agent."
        ),
    )

    @field_validator("base_url")
    @classmethod
    def _normalise_base_url(cls, value: str | None) -> str | None:
        """Trim pasted whitespace and a trailing slash; demand a scheme.

        Without the scheme check a typo surfaces as an opaque client error on
        the first turn of a live call rather than when the connection is saved.
        """
        if value is None:
            return None
        url = value.strip().rstrip("/")
        if not url:
            return None
        if not url.startswith(_URL_SCHEMES):
            raise ValueError("base_url must start with http:// or https://")
        return url


class OpenAICompatibleLLMSettings(BaseLLMSettings):
    """OpenAI sampling knobs, passed through to the endpoint unchanged."""

    history_mode: Literal["inherit", "full", "current_turn"] = Field(
        default="inherit",
        description=(
            "How much of the conversation each turn sends. 'inherit' follows "
            "the endpoint's own setting; 'full' sends every message so far; "
            "'current_turn' sends the system prompt plus the current user turn "
            "only, so the endpoint sees no earlier exchanges."
        ),
        json_schema_extra={
            "examples": ["inherit", "full", "current_turn"],
            "option_labels": {
                "inherit": "Inherit from endpoint",
                "full": "Full conversation",
                "current_turn": "Current turn only",
            },
        },
    )
    system_prompt_mode: Literal["inherit", "send", "omit"] = Field(
        default="inherit",
        description=(
            "Whether the agent's system prompt is sent. 'inherit' follows the "
            "endpoint's own setting; 'send' puts it at the head of every "
            "request; 'omit' leaves it out, for an endpoint that composes its "
            "own instructions and ignores ours."
        ),
        json_schema_extra={
            "examples": ["inherit", "send", "omit"],
            "option_labels": {
                "inherit": "Inherit from endpoint",
                "send": "Send the system prompt",
                "omit": "Endpoint builds its own",
            },
        },
    )
    top_p: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Nucleus sampling cutoff. Unset lets the endpoint decide; 1.0 "
            "considers every token. Tune this or temperature, not both."
        ),
    )
    frequency_penalty: float | None = Field(
        default=None,
        ge=-2.0,
        le=2.0,
        description=(
            "Penalty for tokens by how often they have appeared. Unset lets "
            "the endpoint decide; 0 is no penalty, and 0.1-0.5 curbs a model "
            "that repeats itself on long calls."
        ),
    )
    presence_penalty: float | None = Field(
        default=None,
        ge=-2.0,
        le=2.0,
        description=(
            "Penalty for tokens that appeared at all. Unset lets the endpoint "
            "decide; 0 is no penalty, and 0.1-0.5 pushes the model onto new "
            "topics."
        ),
    )
    seed: int | None = Field(
        default=None,
        description=(
            "Seed for best-effort reproducible sampling. Leave unset for "
            "normal use — fix it only to reproduce a specific run."
        ),
    )
    max_completion_tokens: int | None = Field(
        default=None,
        description=(
            "Maximum completion tokens — the newer name for max_tokens. Set "
            "one or the other, whichever your endpoint documents."
        ),
    )


class OpenAICompatibleLLMConfig(
    OpenAICompatibleAuth,
    OpenAICompatibleLLMSettings,
    BaseLLMConfig,
):
    """OpenAI-compatible LLM served by an operator-supplied endpoint."""

    name: str = "OpenAI-Compatible"

    provider: Literal["openai_compatible"] = "openai_compatible"
    connection_id: str | None = Field(
        default=None,
        description=(
            "Id of the provider connection holding the endpoint and key. "
            "Required on a saved agent; resolved by the runtime at call setup."
        ),
    )
    model: str = Field(
        default="",
        description=(
            "Model id as the endpoint names it — whatever its /v1/models "
            "returns, e.g. 'Qwen/Qwen3-8B-Instruct'."
        ),
        json_schema_extra={"allow_custom_input": True},
    )

    @property
    def effective_history_mode(self) -> HistoryMode:
        """The agent's choice, or the endpoint's default when it defers."""
        if self.history_mode == "inherit":
            return self.endpoint_history_mode
        return self.history_mode

    @property
    def effective_system_prompt_mode(self) -> SystemPromptMode:
        """The agent's choice, or the endpoint's default when it defers."""
        if self.system_prompt_mode == "inherit":
            return self.endpoint_system_prompt_mode
        return self.system_prompt_mode
