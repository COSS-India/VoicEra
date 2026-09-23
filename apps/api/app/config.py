"""Application settings loaded from environment variables."""

import ipaddress
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

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
    PLATFORM_PROVIDER_AUTH: str = Field(
        default="",
        description=(
            "JSON map of provider id → secret fields, used when an organisation "
            'has not connected that provider itself, e.g. {"deepgram":{"api_key":"…"}}. '
            "Empty disables platform credentials entirely. Telephony providers are "
            "never resolved from here — see docs/developer/sandbox-onboarding-plan.md."
        ),
    )
    SANDBOX_SEED_AGENTS: bool = Field(
        default=False,
        description=(
            "Seed the demo agents in app/seed/default_agents.json into every "
            "newly created organisation"
        ),
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

    # --- Rate limiting and abuse control ---
    # See docs/developer/rate-limiting-plan.md.
    RATE_LIMIT_ENABLED: bool = Field(
        default=False,
        description="Master switch for signup/auth/call-admission rate limiting",
    )
    RATE_LIMIT_FAIL_OPEN: bool = Field(
        default=True,
        description="On Redis outage, allow (True) or 503 (False). A limiter outage must not take down signup or calls by default.",
    )
    RATE_LIMIT_IP_SALT: str = Field(
        default="",
        description="Salt for hashing client IPs before they touch Redis or logs. Required when RATE_LIMIT_ENABLED=true. Never reuse SECRET_KEY for this.",
    )
    TRUST_PROXY_HEADERS: bool = Field(
        default=False,
        description="Parse X-Forwarded-For for client IP resolution. Defaults false so a misconfigured deployment fails closed to a proxy IP rather than open to a spoofed header.",
    )
    TRUSTED_PROXY_HOPS: int = Field(
        default=1,
        description="Number of trusted proxy hops between the client and this service. Must be measured against the real deployment, not assumed — see docs/developer/rate-limiting-plan.md §7.",
    )
    RATE_LIMIT_IP_ALLOWLIST: str = Field(
        default="",
        description="Comma-separated IPs/CIDRs (v4 and v6) exempt from per-IP limits. A malformed entry aborts startup.",
    )
    RATE_LIMIT_SCOPE_STALE_SECONDS: int = Field(
        default=900,
        description="Reaper window for scope (e.g. per-IP) concurrency slots — independent of and shorter than the org reaper, see S3b.",
    )
    SIGNUP_ORGS_PER_IP_PER_HOUR: int = Field(default=2)
    SIGNUP_ORGS_PER_IP_PER_DAY: int = Field(default=5)
    SIGNUP_ATTEMPTS_PER_IP_PER_HOUR: int = Field(default=10)
    AUTH_ATTEMPTS_PER_IP_PER_MINUTE: int = Field(default=10)
    RESET_MAILS_PER_EMAIL_PER_HOUR: int = Field(default=3)
    MAX_CONCURRENT_CALLS_PER_IP: int = Field(default=5)
    ORG_DAILY_CALL_SECONDS: int = Field(default=14400)
    MAX_CALL_DURATION_SECONDS: int = Field(default=600)
    MAX_CALL_DURATION_CEILING_SECONDS: int = Field(default=1800)
    RUNTIME_SESSION_SECRET: str = Field(
        default="",
        description="HMAC key for signing/verifying runtime WebSocket admission tokens. Dedicated key — must not reuse SECRET_KEY (see Layer 2b).",
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

    @field_validator("RATE_LIMIT_IP_ALLOWLIST")
    @classmethod
    def _validate_allowlist_entries(cls, value: str) -> str:
        """Reject a malformed entry at startup rather than skip it silently.

        A typo'd CIDR that silently disappears means limits fire against an
        address the operator believes is exempt — that must surface as a
        startup failure, not a confused customer later.
        """
        for entry in (e.strip() for e in value.split(",")):
            if not entry:
                continue
            try:
                ipaddress.ip_network(entry, strict=False)
            except ValueError as exc:
                raise ValueError(
                    f"RATE_LIMIT_IP_ALLOWLIST has an invalid entry {entry!r}: {exc}"
                ) from exc
        return value

    @model_validator(mode="after")
    def _require_ip_salt_when_rate_limiting_enabled(self) -> "Settings":
        """Refuse to start with limiting enabled but no salt to hash IPs with.

        A missing salt would otherwise force a choice between logging raw
        client IPs or silently disabling per-IP limits — neither acceptable.
        """
        if self.RATE_LIMIT_ENABLED and not self.RATE_LIMIT_IP_SALT:
            raise ValueError(
                "RATE_LIMIT_IP_SALT must be set when RATE_LIMIT_ENABLED=true"
            )
        if not self.TRUST_PROXY_HEADERS and self.RATE_LIMIT_IP_ALLOWLIST:
            for entry in (e.strip() for e in self.RATE_LIMIT_IP_ALLOWLIST.split(",")):
                if not entry:
                    continue
                network = ipaddress.ip_network(entry, strict=False)
                if network.is_loopback or network.is_private:
                    logger.error(
                        "RATE_LIMIT_IP_ALLOWLIST contains %s (loopback/private) "
                        "while TRUST_PROXY_HEADERS=false: every request resolves "
                        "to the proxy address in this mode, so this entry exempts "
                        "the entire internet.",
                        entry,
                    )
        return self

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
