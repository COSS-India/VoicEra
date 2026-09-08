"""Register telephony provider config classes and service creators.

Vendor ``config.py`` and ``service.py`` modules are imported by
``load_providers()`` so the catalog and dispatch helpers can discover them.
Keep these maps the single source of registered telephony providers.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from typing import Any, TypeVar, get_type_hints

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from apps.telephony.base import Kind

F = TypeVar("F", bound=Callable[..., Any])

TELEPHONY_CONFIGS: dict[str, type[BaseModel]] = {}
CLIENT_CREATORS: dict[str, Callable[[Any], Any]] = {}
ANSWER_XML_BUILDERS: dict[str, Callable[..., str]] = {}
FRAME_SERIALIZER_FACTORIES: dict[str, Callable[..., Any]] = {}

_LOADED = False
_LOADING = False
_SERIALIZERS_LOADED = False
_SERIALIZERS_LOADING = False


def _normalize_provider(provider: str) -> str:
    name = (provider or "").strip().lower()
    if not name:
        raise ValueError("Telephony provider id is required")
    return name


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
    params = [name for name in hints if name != "return"]
    if not params:
        annotations = getattr(fn, "__annotations__", {})
        params = [name for name in annotations if name != "return"]
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


def _register_named(
    registry: dict[str, Callable[..., Any]],
    provider: str,
    fn: F,
    *,
    label: str,
) -> F:
    pid = _normalize_provider(provider)
    existing = registry.get(pid)
    if existing is not None and existing is not fn:
        raise ValueError(
            f"Duplicate telephony {label} for provider {pid!r}: "
            f"{existing.__module__}.{existing.__name__} and "
            f"{fn.__module__}.{fn.__name__}"
        )
    registry[pid] = fn
    return fn


def register_telephony(cls: type[BaseModel]) -> type[BaseModel]:
    """Register a telephony config class under its ``provider`` id."""
    pid = _provider_id(cls)
    existing = TELEPHONY_CONFIGS.get(pid)
    if existing is not None and existing is not cls:
        raise ValueError(
            f"Duplicate telephony provider id {pid!r}: "
            f"{existing.__name__} and {cls.__name__}"
        )
    TELEPHONY_CONFIGS[pid] = cls
    return cls


def register_client(fn: F) -> F:
    """Register a client creator: ``def create_client(cfg: VobizConfig): ...``."""
    cfg_cls = _config_cls_from_creator(fn)
    provider = _provider_id(cfg_cls)
    existing = CLIENT_CREATORS.get(provider)
    if existing is not None and existing is not fn:
        raise ValueError(
            f"Duplicate telephony client creator for provider {provider!r}: "
            f"{existing.__module__}.{existing.__name__} and "
            f"{fn.__module__}.{fn.__name__}"
        )
    CLIENT_CREATORS[provider] = fn
    return fn


def register_answer_xml(provider: str) -> Callable[[F], F]:
    """Register an answer-stream XML builder for ``provider``."""

    def decorator(fn: F) -> F:
        return _register_named(ANSWER_XML_BUILDERS, provider, fn, label="answer XML")

    return decorator


def register_frame_serializer(provider: str) -> Callable[[F], F]:
    """Register a WebSocket frame serializer factory for ``provider``."""

    def decorator(fn: F) -> F:
        return _register_named(
            FRAME_SERIALIZER_FACTORIES,
            provider,
            fn,
            label="frame serializer",
        )

    return decorator


def load_providers() -> None:
    """Import every vendor ``config`` and ``service`` module under ``providers/``."""
    global _LOADED, _LOADING
    if _LOADED or _LOADING:
        return

    _LOADING = True
    try:
        base = __package__ or "apps.telephony"
        root_name = f"{base}.providers"
        try:
            root = importlib.import_module(root_name)
        except ModuleNotFoundError:
            return
        root_paths = getattr(root, "__path__", None)
        if root_paths is None:
            return
        for mod in pkgutil.iter_modules(root_paths):
            if not mod.ispkg:
                continue
            for submodule in ("config", "service"):
                module_name = f"{root_name}.{mod.name}.{submodule}"
                try:
                    importlib.import_module(module_name)
                except ModuleNotFoundError as exc:
                    if exc.name == module_name or (
                        exc.name and exc.name.endswith(f".{submodule}")
                    ):
                        continue
                    raise
        _LOADED = True
    finally:
        _LOADING = False


def load_frame_serializers() -> None:
    """Import optional per-vendor serializer modules (requires pipecat).

    Not called by ``load_providers()`` so the API can import telephony without
    pipecat installed. Voice runtime should call this indirectly via
    ``get_frame_serializer_factory``.
    """
    global _SERIALIZERS_LOADED, _SERIALIZERS_LOADING
    if _SERIALIZERS_LOADED or _SERIALIZERS_LOADING:
        return

    _SERIALIZERS_LOADING = True
    try:
        load_providers()
        base = __package__ or "apps.telephony"
        root_name = f"{base}.providers"
        try:
            root = importlib.import_module(root_name)
        except ModuleNotFoundError:
            return
        root_paths = getattr(root, "__path__", None)
        if root_paths is None:
            return
        for mod in pkgutil.iter_modules(root_paths):
            if not mod.ispkg:
                continue
            module_name = f"{root_name}.{mod.name}.serializer_service"
            try:
                importlib.import_module(module_name)
            except ModuleNotFoundError as exc:
                if exc.name == module_name or (
                    exc.name and exc.name.endswith(".serializer_service")
                ):
                    continue
                raise
        _SERIALIZERS_LOADED = True
    finally:
        _SERIALIZERS_LOADING = False


def config_classes(kind: Kind | None = None) -> list[type[BaseModel]]:
    """Return registered telephony config classes (``kind`` must be telephony)."""
    load_providers()
    if kind is not None and kind is not Kind.TELEPHONY:
        raise ValueError(f"Unsupported kind: {kind!r}")
    return list(TELEPHONY_CONFIGS.values())


def registered_providers() -> frozenset[str]:
    """Return the set of registered telephony provider ids."""
    load_providers()
    return frozenset(TELEPHONY_CONFIGS)


def get_client_creator(provider: str) -> Callable[[Any], Any]:
    load_providers()
    pid = _normalize_provider(provider)
    creator = CLIENT_CREATORS.get(pid)
    if creator is None:
        raise ValueError(f"Unsupported telephony provider: {provider!r}")
    return creator


def get_answer_xml_builder(provider: str) -> Callable[..., str]:
    load_providers()
    pid = _normalize_provider(provider)
    builder = ANSWER_XML_BUILDERS.get(pid)
    if builder is None:
        raise ValueError(f"Unsupported telephony provider for XML: {provider!r}")
    return builder


def get_frame_serializer_factory(provider: str) -> Callable[..., Any]:
    load_frame_serializers()
    pid = _normalize_provider(provider)
    factory = FRAME_SERIALIZER_FACTORIES.get(pid)
    if factory is None:
        raise ValueError(
            f"Unsupported telephony provider for serializer: {provider!r}"
        )
    return factory


def build_config(provider: str, **data: Any) -> BaseModel:
    """Instantiate the registered config model for ``provider``.

    Raises ``ValueError`` when ``provider`` is not registered.
    """
    load_providers()
    pid = _normalize_provider(provider)
    cls = TELEPHONY_CONFIGS.get(pid)
    if cls is None:
        raise ValueError(f"Unsupported telephony provider: {provider!r}")
    return cls(**data)


def create_client(config: Any):
    """Build a provider HTTP client from a telephony config model."""
    provider = getattr(config, "provider", None)
    if provider is None:
        raise ValueError("Telephony config is missing provider")
    creator = get_client_creator(str(provider))
    return creator(config)
