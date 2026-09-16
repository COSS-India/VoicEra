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
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ...base import BaseLLMConfig, BaseLLMSettings

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
