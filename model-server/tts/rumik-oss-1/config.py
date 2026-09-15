"""Deployment configuration for the rumik-oss-1 slot.

Every knob this folder reads is fetched here, once, with `os.getenv` and a
literal name -- not through a table or a helper that takes the name as an
argument. That is deliberate: `tests/test_engine_env_surface.py` finds what a
model reads by scanning for exactly that shape, and a cleverer lookup would
make this folder look like it reads nothing at all. The test would pass and the
deployment would still be unable to set anything, which is the failure the test
exists to catch.

Every name below is declared in compose.extra.yml. If you add one here, add it
there in the same commit, or the container takes the fallback written on this
line instead of the deployment's value -- silently.

PORT is the exception, and it is not listed. The slot contract sets it and the
Dockerfile's CMD reads it directly. A `RUMIK_PORT` would be a second knob for
one port, where one of the two can never win; indic-mio's overlay records how
that plays out.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

#: Shipped defaults, from the model card's own inference example: t 0.8, top_k
#: 30, 2048 new tokens. Restated here rather than inherited from their
#: server.py, which is not the file this deployment runs.
_TRUE = {"1", "true", "yes", "on"}


def _text(raw: str | None, default: str) -> str:
    return default if raw is None or not raw.strip() else raw.strip()


def _number(raw: str | None, default: float, cast):
    """A malformed value is a configuration error, not a reason to guess.

    Falling back silently is how a typo in `RUMIK_TEMPERATURE` becomes a voice
    that sounds subtly wrong and a deployment nobody can explain.
    """
    if raw is None or not raw.strip():
        return default
    try:
        return cast(raw.strip())
    except ValueError as exc:
        raise ValueError(f"expected a number, got {raw!r}") from exc


def _csv(raw: str | None) -> tuple[str, ...]:
    """Comma-separated list, empty entries dropped. Empty string means none."""
    return tuple(part.strip() for part in (raw or "").split(",") if part.strip())


def _flag(raw: str | None, default: bool) -> bool:
    return default if raw is None or not raw.strip() else raw.strip().lower() in _TRUE


@dataclass(frozen=True)
class Config:
    """One deployment's settings. Frozen so nothing rewrites them per request."""

    # ---- model ----------------------------------------------------------
    model_path: str
    model_name: str
    device: str
    dtype: str
    attn_implementation: str

    # ---- server ---------------------------------------------------------
    host: str
    port: int
    log_level: str
    cors_origins: tuple[str, ...]
    max_concurrency: int
    max_input_chars: int

    # ---- synthesis defaults ---------------------------------------------
    default_voice: str
    default_instructions: str
    temperature: float
    top_k: int
    min_new_tokens: int
    max_new_tokens_default: int
    max_new_tokens_limit: int

    # ---- decode ---------------------------------------------------------
    decoder_device: str
    decode_chunk_frames: int
    decode_context_frames: int

    # ---- warmup ---------------------------------------------------------
    warmup_enabled: bool
    warmup_tokens: int

    @classmethod
    def from_env(cls) -> Config:
        return cls(
            model_path=_text(os.getenv("RUMIK_MODEL_PATH"), "/models/rumik-oss-1"),
            model_name=_text(os.getenv("RUMIK_MODEL_NAME"), "rumik-oss-1"),
            device=_text(os.getenv("RUMIK_DEVICE"), "cuda"),
            dtype=_text(os.getenv("RUMIK_DTYPE"), "bfloat16"),
            attn_implementation=_text(os.getenv("RUMIK_ATTN_IMPLEMENTATION"), "sdpa"),
            # 0.0.0.0 inside the container is correct: the gateway reaches this
            # by Compose service name and nothing is published on the host.
            host=_text(os.getenv("RUMIK_HOST"), "0.0.0.0"),
            # PORT, not RUMIK_PORT -- see the module docstring.
            port=int(_number(os.getenv("PORT"), 8002, int)),
            log_level=_text(os.getenv("RUMIK_LOG_LEVEL"), "INFO").upper(),
            cors_origins=_csv(os.getenv("RUMIK_CORS_ORIGINS")),
            max_concurrency=int(_number(os.getenv("RUMIK_MAX_CONCURRENCY"), 1, int)),
            max_input_chars=int(_number(os.getenv("RUMIK_MAX_INPUT_CHARS"), 1000, int)),
            default_voice=_text(os.getenv("RUMIK_DEFAULT_VOICE"), "Ira"),
            default_instructions=_text(os.getenv("RUMIK_DEFAULT_INSTRUCTIONS"), ""),
            temperature=float(_number(os.getenv("RUMIK_TEMPERATURE"), 0.8, float)),
            top_k=int(_number(os.getenv("RUMIK_TOP_K"), 30, int)),
            min_new_tokens=int(_number(os.getenv("RUMIK_MIN_NEW_TOKENS"), 8, int)),
            max_new_tokens_default=int(
                _number(os.getenv("RUMIK_MAX_NEW_TOKENS_DEFAULT"), 2048, int)
            ),
            max_new_tokens_limit=int(_number(os.getenv("RUMIK_MAX_NEW_TOKENS_LIMIT"), 2048, int)),
            decoder_device=_text(os.getenv("RUMIK_DECODER_DEVICE"), "cuda"),
            decode_chunk_frames=int(_number(os.getenv("RUMIK_DECODE_CHUNK_FRAMES"), 2, int)),
            decode_context_frames=int(
                _number(os.getenv("RUMIK_DECODE_CONTEXT_FRAMES"), 32, int)
            ),
            warmup_enabled=_flag(os.getenv("RUMIK_WARMUP_ENABLED"), True),
            warmup_tokens=int(_number(os.getenv("RUMIK_WARMUP_TOKENS"), 256, int)),
        )

    def __post_init__(self) -> None:
        if self.decode_chunk_frames < 1:
            raise ValueError("RUMIK_DECODE_CHUNK_FRAMES must be at least 1")
        if self.decode_context_frames < self.decode_chunk_frames:
            # The window has to cover the frames it emits, or the tail slice
            # below reaches past the start of the decoded audio and the stream
            # repeats samples it has already sent.
            raise ValueError(
                "RUMIK_DECODE_CONTEXT_FRAMES must be >= RUMIK_DECODE_CHUNK_FRAMES"
            )
        if self.max_concurrency < 1:
            raise ValueError("RUMIK_MAX_CONCURRENCY must be at least 1")
