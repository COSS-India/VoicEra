"""BlueDots LLM configuration.

``api_key`` and ``base_url`` are org-level ProviderAuth (Integrations).
``caller_phone`` rides the Auth layer so it never appears on the agent form —
the runtime merges it in per call. Agent settings are only shared LLM sampling
knobs (temperature / max_tokens).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ...base import BaseLLMConfig, BaseLLMSettings
from .catalog import DEFAULT_MODEL, LLM_MODELS


class BlueDotsAuth(BaseModel):
    api_key: str | list[str] = Field(
        description="API key for the BlueDots endpoint (or a list for rotation).",
        json_schema_extra={"secret": True},
    )
    base_url: str | None = Field(
        default=None,
        description=(
            "BlueDots API base URL (e.g. https://api.example.com/v1). "
            "Leave empty to use the catalog default."
        ),
        json_schema_extra={"secret": True},
    )
    caller_phone: str | None = Field(
        default=None,
        description=(
            "The caller's number for this call, digits only with country code. "
            "Merged in by the runtime per call; never stored on an agent."
        ),
    )


class BlueDotsLLMSettings(BaseLLMSettings):
    """Shared LLM sampling knobs only — endpoint identity lives on Auth."""


class BlueDotsLLMConfig(BlueDotsAuth, BlueDotsLLMSettings, BaseLLMConfig):
    """BlueDots OpenAI-compatible LLM configuration."""

    name: str = "BlueDots"

    provider: Literal["bluedots"] = "bluedots"
    model: str = Field(
        default=DEFAULT_MODEL,
        description="BlueDots model id as the endpoint names it.",
        json_schema_extra={"examples": list(LLM_MODELS)},
    )
