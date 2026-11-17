"""Deployment configuration for the higgs-tts-3 slot.

Every knob this folder reads is fetched here, once, with `os.getenv` and a
literal name. `tests/test_engine_env_surface.py` finds what a model reads by
scanning for exactly that shape, so a table-driven lookup would make this folder
look as if it read nothing. Every name below is declared in compose.extra.yml;
add one here and you add it there in the same commit, or the container quietly
takes the fallback written on this line.

PORT is set by the slot contract and read by the Dockerfile's CMD, so there is
no HIGGS_PORT -- one knob per port.

The sidecar's own settings (memory fractions, the checkpoint id) are not read
here at all: they are flags on the sidecar's command line in compose.extra.yml,
because the adapter never needs to know them.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

_TRUE = {"1", "true", "yes", "on"}


def _text(raw: str | None, default: str) -> str:
    return default if raw is None or not raw.strip() else raw.strip()


def _number(raw: str | None, default, cast):
    """A malformed value is a configuration error, not a reason to guess."""
    if raw is None or not raw.strip():
        return default
    try:
        return cast(raw.strip())
    except ValueError as exc:
        raise ValueError(f"expected a number, got {raw!r}") from exc


def _optional_int(raw: str | None) -> int | None:
    """Empty means "let the sidecar decide", which is different from any number."""
    if raw is None or not raw.strip():
        return None
    return int(_number(raw, 0, int))


def _csv(raw: str | None) -> tuple[str, ...]:
    return tuple(part.strip() for part in (raw or "").split(",") if part.strip())


def _flag(raw: str | None, default: bool) -> bool:
    return default if raw is None or not raw.strip() else raw.strip().lower() in _TRUE


@dataclass(frozen=True)
class Config:
    """One deployment's settings. Frozen so nothing rewrites them per request."""

    # ---- sidecar --------------------------------------------------------
    sidecar_url: str
    sidecar_timeout_s: float
    #: Most simultaneous streams to the sidecar; each holds one connection.
    sidecar_max_connections: int
    #: Where the sidecar sees voices/ (its --allowed-local-media-path).
    sidecar_voices_dir: str

    # ---- this server ----------------------------------------------------
    model_name: str
    voices_dir: str
    host: str
    port: int
    log_level: str
    cors_origins: tuple[str, ...]
    max_input_chars: int
    #: Empty = no auth, which is right behind the gateway (it has none either).
    #: Set it whenever this server is reachable from outside, e.g. a tunnel.
    api_key: str
    #: Refuse to start without api_key. The standalone stack sets this, so a
    #: public tunnel can never front an open GPU by accident.
    require_api_key: bool

    # ---- synthesis defaults ---------------------------------------------
    default_voice: str
    default_instructions: str
    allow_zero_shot: bool
    temperature: float
    top_k: int
    top_p: float
    max_new_tokens_default: int
    max_new_tokens_limit: int
    initial_chunk_frames: int | None

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            sidecar_url=_text(
                os.getenv("HIGGS_SIDECAR_URL"), "http://higgs-sglang:8000"
            ).rstrip("/"),
            sidecar_timeout_s=float(_number(os.getenv("HIGGS_SIDECAR_TIMEOUT_S"), 60.0, float)),
            sidecar_max_connections=int(
                _number(os.getenv("HIGGS_SIDECAR_MAX_CONNECTIONS"), 512, int)
            ),
            sidecar_voices_dir=_text(os.getenv("HIGGS_SIDECAR_VOICES_DIR"), "/voices").rstrip("/"),
            model_name=_text(os.getenv("HIGGS_MODEL_NAME"), "higgs-tts-3"),
            voices_dir=_text(os.getenv("HIGGS_VOICES_DIR"), "/app/voices"),
            host=_text(os.getenv("HIGGS_HOST"), "0.0.0.0"),
            port=int(_number(os.getenv("PORT"), 8002, int)),
            log_level=_text(os.getenv("HIGGS_LOG_LEVEL"), "INFO").upper(),
            cors_origins=_csv(os.getenv("HIGGS_CORS_ORIGINS")),
            max_input_chars=int(_number(os.getenv("HIGGS_MAX_INPUT_CHARS"), 400, int)),
            api_key=_text(os.getenv("HIGGS_API_KEY"), ""),
            require_api_key=_flag(os.getenv("HIGGS_REQUIRE_API_KEY"), False),
            default_voice=_text(os.getenv("HIGGS_DEFAULT_VOICE"), "Aditi"),
            default_instructions=_text(os.getenv("HIGGS_DEFAULT_INSTRUCTIONS"), ""),
            allow_zero_shot=_flag(os.getenv("HIGGS_ALLOW_ZERO_SHOT"), False),
            temperature=float(_number(os.getenv("HIGGS_TEMPERATURE"), 0.8, float)),
            top_k=int(_number(os.getenv("HIGGS_TOP_K"), 50, int)),
            top_p=float(_number(os.getenv("HIGGS_TOP_P"), 0.8, float)),
            max_new_tokens_default=int(
                _number(os.getenv("HIGGS_MAX_NEW_TOKENS_DEFAULT"), 1024, int)
            ),
            max_new_tokens_limit=int(_number(os.getenv("HIGGS_MAX_NEW_TOKENS_LIMIT"), 2048, int)),
            initial_chunk_frames=_optional_int(os.getenv("HIGGS_INITIAL_CHUNK_FRAMES")),
        )

    def __post_init__(self) -> None:
        if self.require_api_key and not self.api_key:
            raise ValueError(
                "HIGGS_REQUIRE_API_KEY is set but HIGGS_API_KEY is empty. Generate one with "
                "`openssl rand -hex 24` and export it as HIGGS_TEST_API_KEY before `up`."
            )
        if self.max_new_tokens_default > self.max_new_tokens_limit:
            raise ValueError(
                "HIGGS_MAX_NEW_TOKENS_DEFAULT must not exceed HIGGS_MAX_NEW_TOKENS_LIMIT "
                f"({self.max_new_tokens_default} > {self.max_new_tokens_limit})"
            )
        if self.max_new_tokens_limit < 1 or self.max_input_chars < 1:
            raise ValueError("HIGGS_MAX_NEW_TOKENS_LIMIT and HIGGS_MAX_INPUT_CHARS must be >= 1")
        if self.initial_chunk_frames is not None and self.initial_chunk_frames < 0:
            raise ValueError("HIGGS_INITIAL_CHUNK_FRAMES must be >= 0 (0 = steady chunk size)")
