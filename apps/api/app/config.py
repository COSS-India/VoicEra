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
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120
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

    # Post-call webhooks (see app/services/call_webhook_service.py)
    CALL_WEBHOOK_SETTLE_SECONDS: int = Field(
        default=20,
        description="Wait after a call ends before sending, so transcript/recording patches land",
    )
    CALL_WEBHOOK_TIMEOUT_SECONDS: float = Field(
        default=10.0,
        description="HTTP timeout for one webhook POST",
    )
    CALL_WEBHOOK_MAX_ATTEMPTS: int = Field(
        default=8,
        description="Attempts before a delivery is marked failed",
    )
    CALL_WEBHOOK_BACKOFF_BASE_SECONDS: int = Field(
        default=30,
        description="First retry delay; doubles each attempt",
    )
    CALL_WEBHOOK_BACKOFF_MAX_SECONDS: int = Field(
        default=3600,
        description="Upper bound on the retry delay",
    )
    CALL_WEBHOOK_LEASE_SECONDS: int = Field(
        default=120,
        description="How long a worker holds a claimed delivery before another may retry it",
    )
    CALL_WEBHOOK_DISPATCH_BATCH: int = Field(
        default=50,
        description="Max deliveries sent per dispatcher run",
    )
    CALL_WEBHOOK_ALLOW_HTTP: bool = Field(
        default=False,
        description="Allow http:// webhook URLs (local development only)",
    )

    # Post-call call_output (see app/services/call_output/)
    CALL_OUTPUT_DELAY_SECONDS: int = Field(
        default=45,
        description="Wait after an answered call ends before working out call_output",
    )
    CALL_OUTPUT_RETRY_SECONDS: int = Field(default=30, description="Delay between call_output attempts")
    CALL_OUTPUT_MAX_ATTEMPTS: int = Field(default=6, description="Attempts before call_output is marked failed")
    CALL_OUTPUT_LEASE_SECONDS: int = Field(default=120, description="Worker lease on a call being computed")
    CALL_OUTPUT_DISPATCH_BATCH: int = Field(default=20, description="Calls computed per dispatcher run")
    CALL_OUTPUT_LOG_GRACE_SECONDS: int = Field(
        default=180,
        description="How long after a call ends missing provider logs mean 'not there yet' rather than 'none'",
    )
    CALL_OUTPUT_WEBHOOK_MAX_WAIT_SECONDS: int = Field(
        default=600,
        description="Longest the post-call webhook waits for call_output before sending without it",
    )
    CALL_OUTPUT_LLM_BASE_URL: str = Field(
        default="",
        description="OpenAI-compatible base URL for reading transcripts (e.g. https://api.openai.com/v1)",
    )
    CALL_OUTPUT_LLM_MODEL: str = Field(default="", description="Model for reading transcripts, e.g. gpt-4.1-mini")
    CALL_OUTPUT_LLM_API_KEY: str = Field(default="", description="API key for the transcript model")
    CALL_OUTPUT_LLM_TIMEOUT_SECONDS: float = Field(default=30.0, description="Timeout per transcript request")
    CALL_OUTPUT_LLM_JSON_MODE: bool = Field(
        default=True,
        description="Send response_format=json_object (turn off for servers that reject it)",
    )
    BLUEDOTS_LOKI_URL: str = Field(
        default="",
        description="AI DPG Loki base URL reachable from the worker, e.g. http://loki:3100",
    )
    BLUEDOTS_LOKI_SELECTOR: str = Field(
        default='{job=~"agent_core|action_gateway"}',
        description="LogQL stream selector for AI DPG's Agent Core and Action Gateway logs",
    )
    BLUEDOTS_LOKI_TIMEOUT_SECONDS: float = Field(default=10.0, description="Timeout per Loki query")

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
