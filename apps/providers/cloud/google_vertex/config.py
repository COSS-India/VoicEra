"""Google Vertex AI LLM configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ...base import BaseLLMConfig, BaseLLMSettings
from .catalog import LLM_MODELS, DEFAULT_LLM_MODEL


class GoogleVertexAuth(BaseModel):
    project_id: str = Field(description="Google Cloud project ID.")
    location: str = Field(
        default="us-central1",
        description="GCP region for the Vertex AI endpoint (e.g. 'us-central1').",
    )
    credentials: str | None = Field(
        default=None,
        description=(
            "Paste the entire service-account JSON file. "
            "If omitted, falls back to Application Default Credentials (ADC)."
        ),
        json_schema_extra={"multiline": True, "secret": True},
    )


class GoogleVertexLLMSettings(BaseLLMSettings):
    """Standard LLM sampling knobs."""


class GoogleVertexLLMConfig(GoogleVertexAuth, GoogleVertexLLMSettings, BaseLLMConfig):
    """Google Gemini LLM via Vertex AI."""

    name: str = "Google Vertex AI"

    provider: Literal["google_vertex"] = "google_vertex"
    model: str = Field(
        default=DEFAULT_LLM_MODEL,
        description="Google Vertex AI publisher/model identifier.",
        json_schema_extra={
            "examples": list(LLM_MODELS),
            "allow_custom_input": True,
        },
    )
