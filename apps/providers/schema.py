"""Dump readable provider catalogs from the registered provider configs.

Vendor ``service.py`` modules register config classes into ``registry``.
This module turns each into a **simplified** catalog entry (not raw JSON
Schema) so a backend API or UI can discover providers, fields, secrets,
and suggested models without schema noise.

Usage::

    from apps.providers import Kind, provider_schemas, configuration_defaults

    openai = provider_schemas(Kind.LLM)["openai"]
    defaults = configuration_defaults()
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from typing import Any, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined

from .base import Kind, ProviderType
from .languages import LANGUAGES, parse_language_ids
from .registry import (
    LLM_CONFIGS,
    STT_CONFIGS,
    TTS_CONFIGS,
    load_providers,
)
from .scoped_settings import (
    CAPABILITIES_KEY,
    get_settings_by_model_language,
)

# Default provider picks for a new configuration UI.
DEFAULT_SERVICE_PROVIDERS: dict[str, str] = {
    Kind.STT.value: "deepgram",
    Kind.TTS.value: "elevenlabs",
    Kind.LLM.value: "openai",
}

_CONFIGS_BY_KIND: dict[Kind, dict[str, type[BaseModel]]] = {
    Kind.STT: STT_CONFIGS,
    Kind.TTS: TTS_CONFIGS,
    Kind.LLM: LLM_CONFIGS,
}

# Structural / discriminator / display fields — catalog top-level, not form fields.
_OMIT_FIELDS = frozenset({"kind", "provider", "name"})

# Extra keys we intentionally surface from Field(json_schema_extra=...).
# allow_custom_input is read for input_mode derivation but not dumped.
_EXTRA_KEYS = (
    "secret",
    "examples",
    "multiline",
    "model_options",
    "language_codes",
    "docs_url",
)


def _union_variants(annotated_union: Any) -> tuple[type[BaseModel], ...]:
    """Extract config classes from ``Annotated[Union[...], Field(...)]``."""
    args = get_args(annotated_union)
    if not args:
        raise TypeError(f"Expected Annotated union, got {annotated_union!r}")
    inner = args[0]
    variants = get_args(inner)
    if not variants:
        raise TypeError(f"Expected Union members inside Annotated, got {inner!r}")
    return variants  # type: ignore[return-value]


def _provider_id(cls: type[BaseModel]) -> str:
    """Return the discriminator value from ``provider: Literal[...] = "..."``."""
    field = cls.model_fields.get("provider")
    if field is None:
        raise ValueError(f"{cls.__name__} has no 'provider' field")
    default = field.default
    if default is PydanticUndefined:
        raise ValueError(f"{cls.__name__}.provider has no default discriminator value")
    return str(default)


def _display_name(cls: type[BaseModel]) -> str:
    """Return the UI display name from ``name: str = "..."``."""
    field = cls.model_fields.get("name")
    if field is None:
        raise ValueError(f"{cls.__name__} has no 'name' field")
    default = field.default
    if default is PydanticUndefined or default is None:
        raise ValueError(f"{cls.__name__}.name has no default display value")
    return str(default)


def _provider_type(cls: type[BaseModel]) -> ProviderType:
    """Derive cloud / adapter / local from the config class module path."""
    module = cls.__module__
    if ".cloud." in module:
        return ProviderType.CLOUD
    if ".adapters." in module:
        return ProviderType.ADAPTER
    if ".local." in module:
        return ProviderType.LOCAL
    raise ValueError(
        f"Cannot derive provider_type for {cls.__name__} "
        f"(module={module!r}). Place configs under "
        f"apps.providers.cloud.*, .adapters.*, or .local.*"
    )


def _type_label(annotation: Any) -> str:
    """Human-readable type string (no JSON Schema anyOf / $ref)."""
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

    if origin is dict:
        if len(args) == 2:
            return f"dict[{_type_label(args[0])}, {_type_label(args[1])}]"
        return "dict"

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
    """Derive options | input | both from examples / model_options + allow_custom."""
    has_options = bool(entry.get("examples")) or bool(entry.get("model_options"))
    if not has_options:
        return "input"
    if raw_extra.get("allow_custom_input") is True:
        return "both"
    return "options"


def _field_catalog(name: str, field: FieldInfo) -> dict[str, Any]:
    """One field entry for the readable catalog."""
    raw_extra = _raw_field_extra(field)
    entry: dict[str, Any] = {
        "type": _type_label(field.annotation),
    }
    if field.description:
        entry["description"] = field.description

    if field.default is not PydanticUndefined and field.default is not None:
        default = field.default
        # Enums / Kind → value
        if hasattr(default, "value") and not isinstance(default, (str, int, float, bool)):
            default = default.value
        entry["default"] = default
    elif field.default is None and not _is_required(field):
        entry["default"] = None

    if field.metadata:
        for meta in field.metadata:
            ge = getattr(meta, "ge", None)
            le = getattr(meta, "le", None)
            if ge is not None:
                entry["minimum"] = ge
            if le is not None:
                entry["maximum"] = le

    entry.update(_field_extra(field))

    if entry.get("secret") is True:
        entry["secret"] = True
    else:
        entry["input_mode"] = _input_mode(entry, raw_extra)

    return entry


def _config_catalog(cls: type[BaseModel]) -> dict[str, Any]:
    """Simplified provider catalog entry (no $defs / $ref / anyOf)."""
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
        "provider_type": _provider_type(cls).value,
    }
    doc = (cls.__doc__ or "").strip()
    if doc:
        catalog["description"] = doc.split("\n", 1)[0].strip()
    if required:
        catalog["required"] = required
    # Always include secrets list so auth is obvious even when empty.
    catalog["secrets"] = secrets
    catalog["fields"] = fields
    scoped = get_settings_by_model_language(cls)
    if scoped is not None:
        lang_codes = (fields.get("language") or {}).get("language_codes") or {}
        catalog[CAPABILITIES_KEY] = {
            model: {
                "languages": dict(
                    lang_codes.get(model)
                    or {lang: lang for lang in by_lang}
                ),
                "settings": by_lang,
            }
            for model, by_lang in scoped.items()
        }
    return catalog


def provider_schemas(kind: Kind) -> dict[str, dict[str, Any]]:
    """Map provider id → simplified catalog for every config of ``kind``.

    Raises ``ValueError`` if two variants share the same provider id.
    """
    load_providers()
    try:
        configs = _CONFIGS_BY_KIND[kind]
    except KeyError as exc:
        raise ValueError(f"Unsupported kind: {kind!r}") from exc

    return {
        provider: _config_catalog(cls)
        for provider, cls in configs.items()
    }


def all_provider_schemas() -> dict[str, dict[str, dict[str, Any]]]:
    """Return ``{"stt": {...}, "tts": {...}, "llm": {...}}`` catalog maps."""
    return {kind.value: provider_schemas(kind) for kind in Kind}


def configuration_defaults() -> dict[str, Any]:
    """Envelope ready for a future ``GET .../configurations/defaults`` route.

    Includes per-kind provider catalogs, ``default_providers``, and the global
    canonical language id → label map (``languages``).
    """
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
        "languages": dict(LANGUAGES),
    }


class UnknownProviderError(KeyError):
    """Raised when a provider id is not registered for a kind."""

    def __init__(self, kind: str, provider: str) -> None:
        self.kind = kind
        self.provider = provider
        super().__init__(f"Unknown {kind} provider: {provider}")


def _config_class(kind: Kind, provider: str) -> type[BaseModel]:
    load_providers()
    try:
        configs = _CONFIGS_BY_KIND[kind]
    except KeyError as exc:
        raise ValueError(f"Unsupported kind: {kind!r}") from exc
    try:
        return configs[provider]
    except KeyError as exc:
        raise UnknownProviderError(kind.value, provider) from exc


def _auth_field_names(cls: type[BaseModel]) -> set[str]:
    """Field names declared on ``*Auth`` bases in the config class MRO."""
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


def _matching_models(
    catalog: dict[str, Any],
    languages: tuple[str, ...],
) -> list[str] | None:
    """Models whose ``model_options`` contain every requested language.

    Returns ``None`` when the catalog has no language map or no model matches.
    """
    lang = catalog.get("fields", {}).get("language")
    if not isinstance(lang, dict):
        return None
    model_options = lang.get("model_options") or {}
    if not model_options:
        return None
    matched = [
        model
        for model, opts in model_options.items()
        if all(lang_id in opts for lang_id in languages)
    ]
    return matched or None


def filter_catalog_by_languages(
    catalog: dict[str, Any],
    languages: str | Sequence[str] | None = None,
) -> dict[str, Any] | None:
    """Return a copy of ``catalog`` trimmed to models that support all languages.

    ``None`` / empty ``languages`` returns a deep copy. Returns ``None`` when
    no model supports every requested id (caller should drop that provider).

    When present, ``capabilities`` keeps only the matched models (same set as
    ``model.examples``); each model's ``languages`` / ``settings`` branches are
    kept in full.
    """
    langs = parse_language_ids(languages)
    if not langs:
        return copy.deepcopy(catalog)

    matched = _matching_models(catalog, langs)
    if matched is None:
        return None

    matched_set = set(matched)
    out = copy.deepcopy(catalog)
    fields = out["fields"]

    if "model" in fields:
        examples = fields["model"].get("examples")
        if examples:
            fields["model"]["examples"] = [m for m in examples if m in matched_set]
        else:
            fields["model"]["examples"] = list(matched)
        if not fields["model"].get("examples"):
            fields["model"]["examples"] = list(matched)

    lang = fields.get("language")
    if isinstance(lang, dict):
        options = lang.get("model_options") or {}
        lang["model_options"] = {m: options[m] for m in matched if m in options}
        codes = lang.get("language_codes") or {}
        if codes:
            lang["language_codes"] = {m: codes[m] for m in matched if m in codes}
        remaining: set[str] = set()
        for opts in lang["model_options"].values():
            remaining.update(opts)
        lang["examples"] = sorted(remaining)

    caps = out.get(CAPABILITIES_KEY)
    if isinstance(caps, dict):
        out[CAPABILITIES_KEY] = {
            model: caps[model] for model in matched if model in caps
        }

    return out


def _provider_summary(catalog: dict[str, Any]) -> dict[str, Any]:
    """Picker identity only — no models / language / model_options."""
    summary: dict[str, Any] = {
        "provider": catalog["provider"],
        "name": catalog["name"],
    }
    if "provider_type" in catalog:
        summary["provider_type"] = catalog["provider_type"]
    return summary


def _strip_model_options(catalog: dict[str, Any]) -> dict[str, Any]:
    """Drop ``model_options`` from language extras (internal filter use only)."""
    language = catalog.get("fields", {}).get("language")
    if isinstance(language, dict):
        language.pop("model_options", None)
    return catalog


def list_providers(
    kind: Kind,
    languages: str | Sequence[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Picker summaries for ``kind``, optionally AND-filtered by language.

    Each entry is ``{provider, name, provider_type?}`` only. Language filter
    keeps a provider when **at least one** model supports every selected id;
    unsupported models are excluded from the settings form, not listed here.
    """
    langs = parse_language_ids(languages)
    listed: dict[str, dict[str, Any]] = {}
    for provider, catalog in provider_schemas(kind).items():
        if langs and kind in (Kind.STT, Kind.TTS):
            filtered = filter_catalog_by_languages(catalog, langs)
            if filtered is None:
                continue
        listed[provider] = _provider_summary(catalog)
    return listed


def provider_settings(
    kind: Kind,
    provider: str,
    languages: str | Sequence[str] | None = None,
) -> dict[str, Any]:
    """Non-auth, non-secret fields for an agent-config form.

    When ``languages`` is set, ``model.examples``, language extras, and
    ``capabilities`` keep only models that support **all** selected ids
    (models that do not are omitted).
    """
    cls = _config_class(kind, provider)
    catalog = _config_catalog(cls)
    auth_names = _auth_field_names(cls)
    secret_names = set(catalog.get("secrets", []))
    keep = {
        name
        for name in catalog["fields"]
        if name not in auth_names and name not in secret_names
    }
    sliced = _slice_catalog(catalog, keep, include_secrets=False)
    langs = parse_language_ids(languages)
    if not langs:
        return _strip_model_options(sliced)
    filtered = filter_catalog_by_languages(sliced, langs)
    if filtered is not None:
        return _strip_model_options(filtered)
    emptied = copy.deepcopy(sliced)
    model = emptied.get("fields", {}).get("model")
    if isinstance(model, dict) and "examples" in model:
        model["examples"] = []
    language = emptied.get("fields", {}).get("language")
    if isinstance(language, dict):
        language.pop("model_options", None)
        if "language_codes" in language:
            language["language_codes"] = {}
        language["examples"] = []
    if CAPABILITIES_KEY in emptied:
        emptied[CAPABILITIES_KEY] = {}
    return emptied


def provider_auth(kind: Kind, provider: str) -> dict[str, Any]:
    """Auth-layer fields for integrations (``*Auth`` MRO plus secrets)."""
    cls = _config_class(kind, provider)
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
    """Auth catalogs for every STT / TTS / LLM provider."""
    return {
        kind.value: {
            provider: provider_auth(kind, provider)
            for provider in provider_schemas(kind)
        }
        for kind in Kind
    }


def provider_auth_by_id(provider: str) -> dict[str, dict[str, Any]]:
    """Auth catalogs for ``provider`` across kinds that register it."""
    found: dict[str, dict[str, Any]] = {}
    for kind in Kind:
        try:
            found[kind.value] = provider_auth(kind, provider)
        except UnknownProviderError:
            continue
    return found


_KIND_ORDER = (Kind.STT.value, Kind.TTS.value, Kind.LLM.value)


def merge_auth_catalogs(
    by_kind: dict[str, dict[str, Any]],
    *,
    kinds: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Merge per-kind auth catalogs into one provider-level entry.

    Fields and secrets are unions. Required is the intersection across kinds
    (empty when schemas diverge, e.g. google Cloud vs AI Studio).
    """
    if not by_kind:
        raise ValueError("by_kind must not be empty")

    ordered_kinds = [
        k for k in (kinds if kinds is not None else _KIND_ORDER) if k in by_kind
    ]
    for kind in by_kind:
        if kind not in ordered_kinds:
            ordered_kinds.append(kind)

    first = by_kind[ordered_kinds[0]]
    fields: dict[str, Any] = {}
    secrets: list[str] = []
    required_sets: list[set[str]] = []

    for kind in ordered_kinds:
        entry = by_kind[kind]
        for name, field in entry.get("fields", {}).items():
            if name not in fields:
                fields[name] = copy.deepcopy(field)
        for name in entry.get("secrets", []):
            if name not in secrets:
                secrets.append(name)
        required_sets.append(set(entry.get("required", [])))

    required: list[str] = []
    if required_sets:
        common = set.intersection(*required_sets) if required_sets else set()
        required = [name for name in fields if name in common]

    out: dict[str, Any] = {
        "provider": first["provider"],
        "name": first["name"],
        "kinds": list(ordered_kinds),
        "fields": fields,
    }
    if "provider_type" in first:
        out["provider_type"] = first["provider_type"]
    if required:
        out["required"] = required
    if secrets:
        out["secrets"] = secrets
    return out


def provider_level_auth(provider: str) -> dict[str, Any] | None:
    """Provider-level auth catalog across STT / TTS / LLM (merged fields)."""
    by_kind = provider_auth_by_id(provider)
    if not by_kind:
        return None
    return merge_auth_catalogs(by_kind)


def all_provider_level_auth() -> dict[str, dict[str, Any]]:
    """Provider-level auth catalogs for every STT / TTS / LLM provider id."""
    providers: set[str] = set()
    for kind in Kind:
        providers.update(provider_schemas(kind))
    result: dict[str, dict[str, Any]] = {}
    for provider in sorted(providers):
        entry = provider_level_auth(provider)
        if entry is not None:
            result[provider] = entry
    return result


__all__ = [
    "DEFAULT_SERVICE_PROVIDERS",
    "UnknownProviderError",
    "provider_schemas",
    "all_provider_schemas",
    "configuration_defaults",
    "filter_catalog_by_languages",
    "list_providers",
    "provider_settings",
    "provider_auth",
    "all_provider_auth",
    "provider_auth_by_id",
    "merge_auth_catalogs",
    "provider_level_auth",
    "all_provider_level_auth",
]
