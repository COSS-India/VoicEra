"""Application settings loaded from environment variables."""

from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent
_ENV_FILE = _ROOT_DIR / ".env"


class Settings(BaseSettings):
    """Runtime configuration for the Voicera API."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Mongo-compatible DB (FerretDB wire protocol)
    MONGODB_HOST: str = "localhost"
    MONGODB_PORT: int = 27017
    MONGODB_USER: str = "admin"
    MONGODB_PASSWORD: str = "admin123"
    MONGODB_DATABASE: str = "voicera"
    # FerretDB uses PostgreSQL users (SCRAM-SHA-256). Leave authSource empty.
    MONGODB_AUTH_SOURCE: str = ""
    MONGODB_AUTH_MECHANISM: str = ""

    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "Voicera API"
    VERSION: str = "0.1.0"
    DEBUG: bool = False

    SECRET_KEY: str = Field(
        default="",
        description="JWT signing key; required in production",
    )
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_ALGORITHM: str = "HS256"

    MAILTRAP_API_TOKEN: str = ""
    MAILTRAP_FROM_EMAIL: str = "noreply@voicera.com"
    MAILTRAP_FROM_NAME: str = "Voicera"
    FRONTEND_URL: str = "http://localhost:3000"

    INTERNAL_API_KEY: str = ""
    PROVIDER_AUTH_ENCRYPTION_KEY: str = Field(
        default="",
        description="Fernet key for encrypting ProviderAuth credential blobs",
    )

    CHROMA_BASE_DIR: str = Field(
        default="app/rag/chroma_data",
        description="Root directory for per-org Chroma knowledge stores",
    )
    KB_EMBEDDING_API_KEY: str = Field(
        default="",
        description="OpenAI API key for knowledge-base embeddings (temporary global key)",
    )
    KB_EMBEDDING_MODEL: str = Field(
        default="text-embedding-3-small",
        description="Embedding model for knowledge-base ingest and retrieval",
    )
    KB_MAX_UPLOAD_BYTES: int = Field(
        default=25 * 1024 * 1024,
        description="Maximum PDF upload size for knowledge base",
    )
    MINIO_BUCKET: str = Field(
        default="voicera-calls",
        description="Default MinIO bucket (call artifacts and KB objects)",
    )
    VOICE_SERVER_BASE_URL: str = Field(
        default="",
        description=(
            "Public base URL of the voice server for telephony answer/hangup webhooks "
            "(e.g. https://voice.example.com)"
        ),
    )

    REDIS_URL: str = Field(
        default="redis://localhost:6379",
        description="Redis URL for ARQ job queue and campaign pub/sub",
    )
    DEFAULT_ORG_CONCURRENCY_LIMIT: int = Field(
        default=10,
        description="Default max concurrent calls per organisation",
    )
    CAMPAIGN_BATCH_SIZE: int = Field(
        default=10,
        description="Default queued runs processed per campaign batch",
    )
    CAMPAIGN_MAX_CSV_BYTES: int = Field(
        default=5 * 1024 * 1024,
        description="Maximum campaign CSV upload size",
    )
    ENABLE_CAMPAIGN_ORCHESTRATOR: bool = Field(
        default=True,
        description="When true, API startup can spawn orchestrator (docker uses separate service)",
    )

    @field_validator("DEBUG", mode="before")
    @classmethod
    def coerce_debug(cls, value: Any) -> bool:
        """Accept common truthy strings; treat anything else as False.

        Host shells often export DEBUG=release / production, which must not
        crash settings parsing.
        """
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return False

    @property
    def mongodb_uri(self) -> str:
        """Build Mongo-compatible connection URI (FerretDB or MongoDB)."""
        uri = (
            f"mongodb://{self.MONGODB_USER}:{self.MONGODB_PASSWORD}"
            f"@{self.MONGODB_HOST}:{self.MONGODB_PORT}/{self.MONGODB_DATABASE}"
        )
        params: list[str] = []
        if self.MONGODB_AUTH_SOURCE:
            params.append(f"authSource={self.MONGODB_AUTH_SOURCE}")
        if self.MONGODB_AUTH_MECHANISM:
            params.append(f"authMechanism={self.MONGODB_AUTH_MECHANISM}")
        if params:
            return f"{uri}?{'&'.join(params)}"
        return uri


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
