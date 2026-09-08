"""Register provider configs / creators, discover vendor modules, shared create helpers.

Each vendor ``service.py`` calls ``@register_stt`` / ``@register_tts`` /
``@register_llm``. The decorator binds the config class (from the typed
first parameter) and the creator function under the config's ``provider``
id. Discriminated unions and ``create_*_service`` dispatch both read from
these maps — one registration, no central if/elif.

``load_providers()`` imports every vendor ``service`` module under
``cloud`` / ``adapters`` / ``local`` so decorators run. Vendor roots are
resolved from this module's package name (``__package__``), not a hardcoded
``apps.providers`` prefix — pytest may import the tree as
``voicera.apps.providers`` when the repo root is on ``sys.path``.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from typing import Any, TypeVar, get_type_hints

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from .base import Kind

F = TypeVar("F", bound=Callable[..., Any])

STT_CONFIGS: dict[str, type[BaseModel]] = {}
TTS_CONFIGS: dict[str, type[BaseModel]] = {}
LLM_CONFIGS: dict[str, type[BaseModel]] = {}

STT_CREATORS: dict[str, Callable[[Any], Any]] = {}
TTS_CREATORS: dict[str, Callable[[Any], Any]] = {}
LLM_CREATORS: dict[str, Callable[[Any], Any]] = {}

_CONFIGS_BY_KIND: dict[Kind, dict[str, type[BaseModel]]] = {
    Kind.STT: STT_CONFIGS,
    Kind.TTS: TTS_CONFIGS,
    Kind.LLM: LLM_CONFIGS,
}

_CREATORS_BY_KIND: dict[Kind, dict[str, Callable[[Any], Any]]] = {
    Kind.STT: STT_CREATORS,
    Kind.TTS: TTS_CREATORS,
    Kind.LLM: LLM_CREATORS,
}

_LOADED = False
_LOADING = False
_VENDOR_SUFFIXES = ("cloud", "adapters", "local")


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def load_providers() -> None:
    """Import every ``*.service`` module under cloud / adapters / local."""
    global _LOADED, _LOADING
    if _LOADED or _LOADING:
        return

    _LOADING = True
    try:
        # ``__package__`` is ``apps.providers`` or ``voicera.apps.providers``.
        base = __package__ or "apps.providers"
        for suffix in _VENDOR_SUFFIXES:
            root_name = f"{base}.{suffix}"
            try:
                root = importlib.import_module(root_name)
            except ModuleNotFoundError:
                continue
            root_paths = getattr(root, "__path__", None)
            if root_paths is None:
                continue
            for mod in pkgutil.iter_modules(root_paths):
                if not mod.ispkg:
                    continue
                service_name = f"{root_name}.{mod.name}.service"
                try:
                    importlib.import_module(service_name)
                except ModuleNotFoundError as exc:
                    # Vendor package without service.py yet — skip.
                    if exc.name == service_name or (
                        exc.name and exc.name.endswith(".service")
                    ):
                        continue
                    raise
        _LOADED = True
    finally:
        _LOADING = False


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def _provider_id(cls: type[BaseModel]) -> str:
    field = cls.model_fields.get("provider")
    if field is None:
        raise ValueError(f"{cls.__name__} has no 'provider' field")
    default = field.default
    if default is PydanticUndefined:
        raise ValueError(f"{cls.__name__}.provider has no default discriminator value")
    return str(default)


def _config_cls_from_creator(fn: Callable[..., Any]) -> type[BaseModel]:
    hints = get_type_hints(fn)
    # First parameter after optional self — creators are plain functions.
    params = [name for name in hints if name != "return"]
    if not params:
        annotations = getattr(fn, "__annotations__", {})
        params = [n for n in annotations if n != "return"]
    if not params:
        raise TypeError(
            f"{fn.__module__}.{fn.__name__} must annotate its config parameter"
        )
    cfg_cls = hints.get(params[0]) or fn.__annotations__[params[0]]
    if not isinstance(cfg_cls, type) or not issubclass(cfg_cls, BaseModel):
        raise TypeError(
            f"{fn.__module__}.{fn.__name__} first parameter must be a "
            f"Pydantic config class, got {cfg_cls!r}"
        )
    return cfg_cls


def _register(kind: Kind, fn: F) -> F:
    cfg_cls = _config_cls_from_creator(fn)
    provider = _provider_id(cfg_cls)
    configs = _CONFIGS_BY_KIND[kind]
    creators = _CREATORS_BY_KIND[kind]
    if provider in configs and configs[provider] is not cfg_cls:
        raise ValueError(
            f"Duplicate {kind.value} provider {provider!r}: "
            f"{configs[provider].__name__} vs {cfg_cls.__name__}"
        )
    configs[provider] = cfg_cls
    creators[provider] = fn
    return fn


def register_stt(fn: F) -> F:
    """Register an STT creator: ``def create_stt(cfg: SomeSTTConfig): ...``."""
    return _register(Kind.STT, fn)


def register_tts(fn: F) -> F:
    """Register a TTS creator: ``def create_tts(cfg: SomeTTSConfig): ...``."""
    return _register(Kind.TTS, fn)


def register_llm(fn: F) -> F:
    """Register an LLM creator: ``def create_llm(cfg: SomeLLMConfig): ...``."""
    return _register(Kind.LLM, fn)


def get_creator(kind: Kind, provider: str) -> Callable[[Any], Any]:
    load_providers()
    creators = _CREATORS_BY_KIND[kind]
    if provider not in creators:
        raise ValueError(f"Unsupported {kind.value} provider: {provider}")
    return creators[provider]


def config_classes(kind: Kind) -> tuple[type[BaseModel], ...]:
    """Registered config classes for ``kind``, sorted by provider id."""
    load_providers()
    return tuple(
        _CONFIGS_BY_KIND[kind][provider]
        for provider in sorted(_CONFIGS_BY_KIND[kind])
    )


# ---------------------------------------------------------------------------
# Helpers used by vendor creators (kept here to avoid factory ↔ service cycles)
# ---------------------------------------------------------------------------


def api_key(value: str | list[str] | None) -> str | None:
    """Resolve a single API key from a string or rotation list."""
    if value is None:
        return None
    if isinstance(value, list):
        if not value:
            raise ValueError("api_key list is empty")
        return value[0]
    return value


def llm_settings(cfg: Any) -> dict[str, Any]:
    """Pipecat LLM settings built only from fields present on the config."""
    settings: dict[str, Any] = {"model": cfg.model}
    if cfg.temperature is not None:
        settings["temperature"] = cfg.temperature
    if cfg.max_tokens is not None:
        settings["max_tokens"] = cfg.max_tokens
    return settings


__all__ = [
    "STT_CONFIGS",
    "TTS_CONFIGS",
    "LLM_CONFIGS",
    "STT_CREATORS",
    "TTS_CREATORS",
    "LLM_CREATORS",
    "load_providers",
    "register_stt",
    "register_tts",
    "register_llm",
    "config_classes",
    "get_creator",
    "api_key",
    "llm_settings",
]
