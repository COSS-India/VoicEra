"""Azure OpenAI LLM configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ...base import BaseLLMConfig, BaseLLMSettings
from .catalog import LLM_MODELS, DEFAULT_LLM_MODEL


class AzureOpenAIAuth(BaseModel):
    api_key: str | list[str] = Field(
        description="Azure OpenAI API key.",
        json_schema_extra={"secret": True},
    )
    endpoint: str = Field(
        description=(
            "Azure OpenAI resource endpoint "
            "(e.g. https://<resource-name>.openai.azure.com)."
        ),
    )


class AzureOpenAILLMSettings(BaseLLMSettings):
    """Standard LLM sampling knobs."""


class AzureOpenAILLMConfig(AzureOpenAIAuth, AzureOpenAILLMSettings, BaseLLMConfig):
    """Azure OpenAI LLM configuration."""

    name: str = "Azure OpenAI"

    provider: Literal["azure_openai"] = "azure_openai"
    model: str = Field(
        default=DEFAULT_LLM_MODEL,
        description="Azure deployment name (not the upstream OpenAI model id).",
        json_schema_extra={
            "examples": list(LLM_MODELS),
            "allow_custom_input": True,
        },
    )
