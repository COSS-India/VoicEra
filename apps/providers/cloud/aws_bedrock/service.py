"""Build Pipecat (or adapter) services from this vendor's configs."""

from __future__ import annotations

from ...registry import register_llm, llm_settings
from .config import AWSBedrockLLMConfig


@register_llm
def create_llm(cfg: AWSBedrockLLMConfig):
    from pipecat.services.aws.llm import AWSBedrockLLMService, AWSBedrockLLMSettings

    return AWSBedrockLLMService(
        aws_access_key=cfg.aws_access_key,
        aws_secret_key=cfg.aws_secret_key,
        aws_region=cfg.aws_region,
        settings=AWSBedrockLLMSettings(**llm_settings(cfg)),
    )

