"""Dump readable telephony provider catalogs from registered configs.

Mirrors ``apps.providers.schema`` so a backend API or UI can discover
telephony providers, auth secrets, Integrations model names, and base URLs.

Usage::

    from apps.telephony import Kind, provider_schemas, configuration_telephony

    vobiz = provider_schemas(Kind.TELEPHONY)["vobiz"]
    defaults = configuration_telephony()
"""

from __future__ import annotations

from typing import Any, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from apps.telephony.base import Kind
from apps.telephony.registry import TELEPHONY_CONFIGS, load_providers

DEFAULT_SERVICE_PROVIDERS: dict[str, str] = {
    Kind.TELEPHONY.value: "vobiz",
}

_OMIT_FIELDS = frozenset({"kind", "provider", "name"})

_EXTRA_KEYS = (
    "secret",
    "examples",
    "multiline",
    "docs_url",
    "integration_model",
)


def _provider_id(cls: type[BaseModel]) -> str:
    field = cls.model_fields.get("provider")
    if field is None:
        raise ValueError(f"{cls.__name__} has no 'provider' field")
    default = field.default
    if default is PydanticUndefined:
        raise ValueError(f"{cls.__name__}.provider has no default discriminator value")
    return str(default)


def _display_name(cls: type[BaseModel]) -> str:
    field = cls.model_fields.get("name")
    if field is None:
        raise ValueError(f"{cls.__name__} has no 'name' field")
    default = field.default
    if default is PydanticUndefined or default is None:
        raise ValueError(f"{cls.__name__}.name has no default display value")
    return str(default)


def _type_label(annotation: Any) -> str:
    import types
    from typing import Literal, Union

    if annotation is None:
        return "any"

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin in (Union, types.UnionType):
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1 and type(None) in args:
            return f"{_type_label(non_none[0])} | null"
        return " | ".join(_type_label(a) for a in args)

    if origin is list:
        inner = _type_label(args[0]) if args else "any"
        return f"list[{inner}]"

    if origin is Literal:
        return "string"

    if origin is not None:
        return getattr(origin, "__name__", str(origin))

    if annotation is type(None):
        return "null"
    if hasattr(annotation, "__name__"):
        return {
            "str": "string",
            "int": "integer",
            "float": "number",
            "bool": "boolean",
        }.get(annotation.__name__, annotation.__name__)
    return str(annotation)


def _raw_field_extra(field: FieldInfo) -> dict[str, Any]:
    extra = field.json_schema_extra
    if not isinstance(extra, dict):
        return {}
    return dict(extra)


def _field_extra(field: FieldInfo) -> dict[str, Any]:
    extra = _raw_field_extra(field)
    return {k: extra[k] for k in _EXTRA_KEYS if k in extra}


def _is_required(field: FieldInfo) -> bool:
    return field.is_required()


def _input_mode(entry: dict[str, Any], raw_extra: dict[str, Any]) -> str:
    has_options = bool(entry.get("examples"))
    if not has_options:
        return "input"
    if raw_extra.get("allow_custom_input") is True:
        return "both"
    return "options"


def _field_catalog(name: str, field: FieldInfo) -> dict[str, Any]:
    raw_extra = _raw_field_extra(field)
    entry: dict[str, Any] = {
        "type": _type_label(field.annotation),
    }
    if field.description:
        entry["description"] = field.description

    if field.default is not PydanticUndefined and field.default is not None:
        default = field.default
        if hasattr(default, "value") and not isinstance(default, (str, int, float, bool)):
            default = default.value
        entry["default"] = default
    elif field.default is None and not _is_required(field):
        entry["default"] = None

    entry.update(_field_extra(field))

    if entry.get("secret") is True:
        entry["secret"] = True
    else:
        entry["input_mode"] = _input_mode(entry, raw_extra)

    return entry


def _config_catalog(cls: type[BaseModel]) -> dict[str, Any]:
    fields: dict[str, dict[str, Any]] = {}
    required: list[str] = []
    secrets: list[str] = []

    for name, field in cls.model_fields.items():
        if name in _OMIT_FIELDS:
            continue
        fields[name] = _field_catalog(name, field)
        if _is_required(field):
            required.append(name)
        if fields[name].get("secret") is True:
            secrets.append(name)

    catalog: dict[str, Any] = {
        "provider": _provider_id(cls),
        "name": _display_name(cls),
    }
    doc = (cls.__doc__ or "").strip()
    if doc:
        catalog["description"] = doc.split("\n", 1)[0].strip()
    if required:
        catalog["required"] = required
    catalog["secrets"] = secrets
    catalog["fields"] = fields
    return catalog


def provider_schemas(kind: Kind = Kind.TELEPHONY) -> dict[str, dict[str, Any]]:
    """Map provider id → simplified catalog for telephony configs."""
    load_providers()
    if kind is not Kind.TELEPHONY:
        raise ValueError(f"Unsupported kind: {kind!r}")
    return {
        provider: _config_catalog(cls)
        for provider, cls in TELEPHONY_CONFIGS.items()
    }


def all_provider_schemas() -> dict[str, dict[str, dict[str, Any]]]:
    """Return ``{"telephony": {...}}`` catalog map."""
    return {Kind.TELEPHONY.value: provider_schemas(Kind.TELEPHONY)}


def configuration_telephony() -> dict[str, Any]:
    """Envelope ready for a backend ``GET .../telephony/defaults``-style route."""
    schemas = all_provider_schemas()
    for kind_key, provider in DEFAULT_SERVICE_PROVIDERS.items():
        if provider not in schemas.get(kind_key, {}):
            raise ValueError(
                f"DEFAULT_SERVICE_PROVIDERS[{kind_key!r}]={provider!r} "
                f"is not a registered provider"
            )
    return {
        **schemas,
        "default_providers": dict(DEFAULT_SERVICE_PROVIDERS),
    }


class UnknownProviderError(KeyError):
    """Raised when a telephony provider id is not registered."""

    def __init__(self, provider: str) -> None:
        self.kind = Kind.TELEPHONY.value
        self.provider = provider
        super().__init__(f"Unknown telephony provider: {provider}")


def _config_class(provider: str) -> type[BaseModel]:
    load_providers()
    try:
        return TELEPHONY_CONFIGS[provider]
    except KeyError as exc:
        raise UnknownProviderError(provider) from exc


def _auth_field_names(cls: type[BaseModel]) -> set[str]:
    names: set[str] = set()
    for base in cls.__mro__:
        if base is cls or not isinstance(base, type):
            continue
        try:
            if not issubclass(base, BaseModel):
                continue
        except TypeError:
            continue
        if not base.__name__.endswith("Auth"):
            continue
        names.update(name for name in base.model_fields if name not in _OMIT_FIELDS)
    return names


def _slice_catalog(
    catalog: dict[str, Any],
    keep: set[str],
    *,
    include_secrets: bool,
) -> dict[str, Any]:
    fields = {name: field for name, field in catalog["fields"].items() if name in keep}
    out: dict[str, Any] = {
        key: value
        for key, value in catalog.items()
        if key not in {"fields", "required", "secrets"}
    }
    out["fields"] = fields
    required = [name for name in catalog.get("required", []) if name in fields]
    if required:
        out["required"] = required
    if include_secrets:
        out["secrets"] = [name for name in catalog.get("secrets", []) if name in fields]
    return out


def _provider_summary(catalog: dict[str, Any]) -> dict[str, Any]:
    return {
        "provider": catalog["provider"],
        "name": catalog["name"],
    }


def list_providers() -> dict[str, dict[str, Any]]:
    """Picker summaries for every telephony provider."""
    return {
        provider: _provider_summary(catalog)
        for provider, catalog in provider_schemas(Kind.TELEPHONY).items()
    }


def provider_settings(provider: str) -> dict[str, Any]:
    """Non-auth, non-secret fields for a telephony config form."""
    cls = _config_class(provider)
    catalog = _config_catalog(cls)
    auth_names = _auth_field_names(cls)
    secret_names = set(catalog.get("secrets", []))
    keep = {
        name
        for name in catalog["fields"]
        if name not in auth_names and name not in secret_names
    }
    return _slice_catalog(catalog, keep, include_secrets=False)


def provider_auth(provider: str) -> dict[str, Any]:
    """Auth-layer fields for integrations."""
    cls = _config_class(provider)
    catalog = _config_catalog(cls)
    auth_names = _auth_field_names(cls)
    secret_names = set(catalog.get("secrets", []))
    keep = {
        name
        for name in catalog["fields"]
        if name in auth_names or name in secret_names
    }
    return _slice_catalog(catalog, keep, include_secrets=True)


def all_provider_auth() -> dict[str, dict[str, dict[str, Any]]]:
    """Auth catalogs keyed as ``{"telephony": {provider: ...}}``."""
    return {
        Kind.TELEPHONY.value: {
            provider: provider_auth(provider)
            for provider in provider_schemas(Kind.TELEPHONY)
        }
    }


def provider_level_auth(provider: str) -> dict[str, Any] | None:
    """Provider-level auth catalog for a telephony provider (single kind)."""
    try:
        entry = provider_auth(provider)
    except UnknownProviderError:
        return None
    out = dict(entry)
    out["kinds"] = [Kind.TELEPHONY.value]
    return out


def all_provider_level_auth() -> dict[str, dict[str, Any]]:
    """Provider-level auth catalogs for every telephony provider."""
    return {
        provider: auth
        for provider in provider_schemas(Kind.TELEPHONY)
        if (auth := provider_level_auth(provider)) is not None
    }


__all__ = [
    "DEFAULT_SERVICE_PROVIDERS",
    "UnknownProviderError",
    "provider_schemas",
    "all_provider_schemas",
    "configuration_telephony",
    "list_providers",
    "provider_settings",
    "provider_auth",
    "all_provider_auth",
    "provider_level_auth",
    "all_provider_level_auth",
]
