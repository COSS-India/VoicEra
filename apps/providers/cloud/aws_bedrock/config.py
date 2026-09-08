"""AWS Bedrock LLM configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ...base import BaseLLMConfig, BaseLLMSettings
from .catalog import LLM_MODELS, DEFAULT_LLM_MODEL


class AWSBedrockAuth(BaseModel):
    aws_access_key: str = Field(
        description="AWS access key ID with bedrock:InvokeModel permission.",
        json_schema_extra={"secret": True},
    )
    aws_secret_key: str = Field(
        description="AWS secret access key paired with the access key ID.",
        json_schema_extra={"secret": True},
    )
    aws_region: str = Field(
        default="us-east-1",
        description="AWS region where the Bedrock model is available.",
    )


class AWSBedrockLLMSettings(BaseLLMSettings):
    """Standard LLM sampling knobs."""


class AWSBedrockLLMConfig(AWSBedrockAuth, AWSBedrockLLMSettings, BaseLLMConfig):
    """AWS Bedrock LLM configuration."""

    name: str = "AWS Bedrock"

    provider: Literal["aws_bedrock"] = "aws_bedrock"
    model: str = Field(
        default=DEFAULT_LLM_MODEL,
        description=(
            "Bedrock model ID — include the region inference-profile prefix "
            "(e.g. 'us.amazon.nova-pro-v1:0')."
        ),
        json_schema_extra={
            "examples": list(LLM_MODELS),
            "allow_custom_input": True,
        },
    )
