"""Base Pydantic models for STT, TTS, and LLM provider configurations.

Each vendor `config.py` declares three layers:

- Auth: credentials and account identity
- Settings: vendor knobs (voice, speed, base_url, …)
- Config: Auth + Settings + provider / model / language

Config classes inherit those three layers. Credentials never live on the bases.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from enum import Enum


class Kind(str, Enum):
    STT = "stt"
    TTS = "tts"
    LLM = "llm"


class ProviderType(str, Enum):
    """Where a provider implementation lives in the package layout."""

    CLOUD = "cloud"
    ADAPTER = "adapter"
    LOCAL = "local"


class BaseProviderConfig(BaseModel):
    """Common fields shared by every provider configuration."""

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
    )

    kind: Kind


class BaseSTTConfig(BaseProviderConfig):
    """Base for all speech-to-text provider configs."""

    kind: Kind = Kind.STT
    name: str = Field(description="Display name shown in the UI.")
    provider: str
    model: str = Field(description="STT model identifier.")
    language: str = Field(
        default="en",
        description=(
            "Canonical language id for transcription. "
            "Use 'multi' where the provider supports auto-detection."
        ),
    )


class BaseTTSSettings(BaseModel):
    """Vendor TTS knobs. Every TTS config inherits a concrete subclass."""

    voice: str = Field(description="Voice name or ID.")


class BaseTTSConfig(BaseProviderConfig):
    """Base for all text-to-speech provider configs."""

    kind: Kind = Kind.TTS
    name: str = Field(description="Display name shown in the UI.")
    provider: str
    model: str = Field(description="TTS model identifier.")
    language: str = Field(
        default="en",
        description="Canonical language id for synthesis.",
    )


class BaseLLMSettings(BaseModel):
    """Shared LLM sampling knobs. Vendor Settings subclass this when needed."""

    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description="Sampling temperature.",
    )
    max_tokens: int | None = Field(
        default=None,
        description="Maximum tokens to generate.",
    )


class BaseLLMConfig(BaseProviderConfig):
    """Base for all LLM provider configs."""

    kind: Kind = Kind.LLM
    name: str = Field(description="Display name shown in the UI.")
    provider: str
    model: str = Field(description="LLM model identifier.")
