"""Build Pipecat UpdateSettings deltas from agent config blobs."""

from __future__ import annotations

from typing import Any, Literal

from pipecat.services.settings import LLMSettings, STTSettings, TTSSettings

ServiceKind = Literal["stt", "tts", "llm"]


def _settings_class(service: Any) -> type | None:
    return getattr(type(service), "Settings", None)


def _mapping_for_kind(kind: ServiceKind, config: dict[str, Any]) -> dict[str, Any]:
    if kind == "stt":
        return {
            k: config[k]
            for k in ("model", "language")
            if config.get(k) is not None
        }
    if kind == "tts":
        mapping = {
            k: config[k]
            for k in ("model", "voice", "language")
            if config.get(k) is not None
        }
        if config.get("speed") is not None:
            mapping["speed"] = config["speed"]
        if config.get("volume") is not None:
            mapping["volume"] = config["volume"]
        return mapping
    return {
        k: config[k]
        for k in ("model", "temperature", "max_tokens", "top_p", "top_k")
        if config.get(k) is not None
    }


def _cartesia_tts_delta(config: dict[str, Any], service: Any) -> Any:
    from pipecat.services.cartesia.tts import GenerationConfig

    settings_cls = _settings_class(service)
    if settings_cls is None:
        return TTSSettings.from_mapping(_mapping_for_kind("tts", config))

    generation = None
    if config.get("speed") is not None or config.get("volume") is not None:
        generation = GenerationConfig(
            speed=config.get("speed", 1.0),
            volume=config.get("volume", 1.0),
        )

    kwargs: dict[str, Any] = {}
    if config.get("model") is not None:
        kwargs["model"] = config["model"]
    if config.get("voice") is not None:
        kwargs["voice"] = config["voice"]
    if config.get("language") is not None:
        kwargs["language"] = config["language"]
    if generation is not None:
        kwargs["generation_config"] = generation
    return settings_cls(**kwargs)


def build_settings_delta(
    kind: ServiceKind,
    config: dict[str, Any],
    *,
    service: Any,
) -> STTSettings | TTSSettings | LLMSettings:
    """Return a sparse settings delta for the given config and live service."""
    provider = str(config.get("provider") or "").strip()

    if kind == "tts" and provider == "cartesia":
        return _cartesia_tts_delta(config, service)

    mapping = _mapping_for_kind(kind, config)
    settings_cls = _settings_class(service)
    if settings_cls is not None and hasattr(settings_cls, "from_mapping"):
        return settings_cls.from_mapping(mapping)

    if kind == "stt":
        return STTSettings.from_mapping(mapping)
    if kind == "tts":
        return TTSSettings.from_mapping(mapping)
    return LLMSettings.from_mapping(mapping)
