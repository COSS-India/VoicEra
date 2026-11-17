"""Deployment settings for the maya2-native slot, read once from the environment.

Every variable here is declared in this folder's compose.extra.yml -- that file,
not this one, is where a deployment's values live. The defaults below repeat the
compose defaults so the server is also runnable by hand, and
tests/test_engine_env_surface.py fails if one is read here and declared nowhere.

No third-party imports: tests load this module without torch, aiohttp or maya3.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

TRUE = {"1", "true", "yes", "on"}
FALSE = {"0", "false", "no", "off"}


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value.strip() == "" else value.strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name, str(default))
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"{name}={raw!r} is not an integer") from None


def _env_float(name: str, default: float) -> float:
    raw = _env(name, str(default))
    try:
        return float(raw)
    except ValueError:
        raise ValueError(f"{name}={raw!r} is not a number") from None


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name, "true" if default else "false").lower()
    if raw in TRUE:
        return True
    if raw in FALSE:
        return False
    raise ValueError(f"{name}={raw!r} is not a boolean (true/false)")


@dataclass(frozen=True)
class Config:
    # --- model -------------------------------------------------------------
    model_path: str = "/models/maya2-native"  # release dir fetch.sh writes, or a HF repo id
    mimi_dir: str = "/models/mimi"  # kyutai/mimi, fetched beside it
    ecapa_dir: str = "/models/ecapa"  # speechbrain/spkrec-ecapa-voxceleb
    model_name: str = "maya2-native"  # reported at /v1/models; equal to the folder id
    device: str = "cuda"

    # --- engine ------------------------------------------------------------
    max_seats: int = 16  # concurrent streams batched per 80 ms tick
    capacity: int = 2048  # KV tokens per seat (prompt + generated frames)
    depth_dtype: str = "fp16"  # upstream's default; closest to fp32 greedy

    # --- admission ---------------------------------------------------------
    max_pending: int = 0  # 0 = same as max_seats
    queue_deadline_ms: float = 2000.0
    http_max_lag_s: float = 120.0

    # --- requests ----------------------------------------------------------
    default_voice: str = "Ahana"
    default_format: str = "pcm"
    normalise: bool = True
    voice_cloning: bool = False

    # --- server ------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8002
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> Config:
        d = cls()
        cfg = cls(
            model_path=_env("MAYA_MODEL_PATH", d.model_path),
            mimi_dir=_env("MAYA_MIMI_DIR", d.mimi_dir),
            ecapa_dir=_env("MAYA_ECAPA_DIR", d.ecapa_dir),
            model_name=_env("MAYA_MODEL_NAME", d.model_name),
            device=_env("MAYA_DEVICE", d.device),
            max_seats=_env_int("MAYA_MAX_SEATS", d.max_seats),
            capacity=_env_int("MAYA_CAPACITY", d.capacity),
            depth_dtype=_env("MAYA_DEPTH_DTYPE", d.depth_dtype).lower(),
            max_pending=_env_int("MAYA_MAX_PENDING", d.max_pending),
            queue_deadline_ms=_env_float("MAYA_QUEUE_DEADLINE_MS", d.queue_deadline_ms),
            http_max_lag_s=_env_float("MAYA_HTTP_MAX_LAG_S", d.http_max_lag_s),
            default_voice=_env("MAYA_DEFAULT_VOICE", d.default_voice),
            default_format=_env("MAYA_DEFAULT_FORMAT", d.default_format).lower(),
            normalise=_env_bool("MAYA_NORMALISE", d.normalise),
            voice_cloning=_env_bool("MAYA_VOICE_CLONING", d.voice_cloning),
            host=_env("MAYA_HOST", d.host),
            # PORT is the slot contract's knob, and the only one: there is no
            # MAYA_PORT, for the reason indic-mio's MIO_PORT is documented as dead.
            port=_env_int("PORT", d.port),
            log_level=_env("MAYA_LOG_LEVEL", d.log_level).upper(),
        )
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if self.max_seats < 1:
            raise ValueError("MAYA_MAX_SEATS must be >= 1")
        if self.capacity < 256:
            raise ValueError("MAYA_CAPACITY must be >= 256 KV tokens")
        if self.depth_dtype not in ("fp16", "bf16", "fp32"):
            raise ValueError("MAYA_DEPTH_DTYPE must be fp16, bf16 or fp32")
        if self.max_pending < 0:
            raise ValueError("MAYA_MAX_PENDING must be >= 0 (0 means MAYA_MAX_SEATS)")
        if self.queue_deadline_ms <= 0:
            raise ValueError("MAYA_QUEUE_DEADLINE_MS must be > 0")
        # Imported here rather than at the top so a bad value names the variable.
        from contract import SPEECH_FORMATS

        if self.default_format not in SPEECH_FORMATS:
            raise ValueError(f"MAYA_DEFAULT_FORMAT must be one of {', '.join(SPEECH_FORMATS)}")

    @property
    def pending_limit(self) -> int:
        return self.max_pending or self.max_seats

    def engine_kwargs(self) -> dict:
        """EngineConfig fields. Everything not named keeps upstream's measured default."""
        return {
            "max_seats": self.max_seats,
            "capacity": self.capacity,
            "depth_dtype": self.depth_dtype,
        }
