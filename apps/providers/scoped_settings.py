"""Per-model / per-language settings overlays for STT and TTS providers.

Vendor catalogs declare capabilities (languages + settings). Schema dumps use::

    settings_by_model_language:
      model → canonical_language → setting → { default, options?, ... }
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

# Top-level key on provider catalog dumps / config class extras.
SETTINGS_BY_MODEL_LANGUAGE_KEY = "settings_by_model_language"

# Top-level API key: model → { languages: {canonical: vendor}, settings: {...} }
CAPABILITIES_KEY = "capabilities"

# Allowed leaf keys for a single setting under (model, language).
LEAF_KEYS = frozenset(
    {
        "default",
        "options",
        "minimum",
        "maximum",
        "input_type",
        "allow_custom_input",
        "description",
    }
)

INPUT_TYPES = frozenset({"dropdown", "slider", "input", "both"})

# model → canonical language → setting_name → leaf meta
SettingsByModelLanguage = dict[str, dict[str, dict[str, dict[str, Any]]]]


def _normalize_leaf(meta: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(meta, Mapping):
        raise TypeError(f"setting meta must be a mapping, got {type(meta)!r}")
    out: dict[str, Any] = {}
    for key, value in meta.items():
        if key not in LEAF_KEYS:
            raise ValueError(f"Unknown settings leaf key: {key!r}")
        if key == "options":
            if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
                raise TypeError(f"options must be a sequence, got {type(value)!r}")
            out["options"] = list(value)
        elif key == "input_type":
            if value not in INPUT_TYPES:
                raise ValueError(
                    f"input_type must be one of {sorted(INPUT_TYPES)}, got {value!r}"
                )
            out["input_type"] = value
        elif key == "allow_custom_input":
            out["allow_custom_input"] = bool(value)
        else:
            out[key] = value
    return out


def normalize_settings_by_model_language(
    tree: Mapping[str, Mapping[str, Mapping[str, Mapping[str, Any]]]],
) -> SettingsByModelLanguage:
    """Return a deep-copied, validated settings tree."""
    normalized: SettingsByModelLanguage = {}
    for model, by_lang in tree.items():
        if not isinstance(model, str) or not model:
            raise ValueError(f"model key must be a non-empty str, got {model!r}")
        if not isinstance(by_lang, Mapping):
            raise TypeError(
                f"settings for model {model!r} must be a mapping, got {type(by_lang)!r}"
            )
        lang_map: dict[str, dict[str, dict[str, Any]]] = {}
        for lang, settings in by_lang.items():
            if not isinstance(lang, str) or not lang:
                raise ValueError(
                    f"language key under {model!r} must be a non-empty str, got {lang!r}"
                )
            if not isinstance(settings, Mapping):
                raise TypeError(
                    f"settings for ({model!r}, {lang!r}) must be a mapping, "
                    f"got {type(settings)!r}"
                )
            field_map: dict[str, dict[str, Any]] = {}
            for name, meta in settings.items():
                if not isinstance(name, str) or not name:
                    raise ValueError(
                        f"setting name under ({model!r}, {lang!r}) must be "
                        f"a non-empty str, got {name!r}"
                    )
                field_map[name] = _normalize_leaf(meta)
            lang_map[lang] = field_map
        normalized[model] = lang_map
    return normalized


def resolve_settings(
    tree: Mapping[str, Mapping[str, Mapping[str, Mapping[str, Any]]]],
    model: str,
    language: str,
) -> dict[str, dict[str, Any]]:
    """Resolve setting meta for ``(model, language)`` (canonical language id).

    Returns an empty dict when the model is unknown or has no matching branch.
    """
    by_lang = tree.get(model)
    if not by_lang:
        return {}
    if language in by_lang:
        return dict(by_lang[language])
    return {}


def settings_schema_extra(
    tree: Mapping[str, Mapping[str, Mapping[str, Mapping[str, Any]]]],
) -> dict[str, Any]:
    """Build ``json_schema_extra`` / class-level catalog payload for a config."""
    return {
        SETTINGS_BY_MODEL_LANGUAGE_KEY: normalize_settings_by_model_language(tree),
    }


def get_settings_by_model_language(
    cls: type[Any],
) -> SettingsByModelLanguage | None:
    """Read a settings tree from a config class if one is declared.

    Looks for, in order:
    1. Class attribute ``settings_by_model_language``
    2. ``model_config['json_schema_extra'][SETTINGS_BY_MODEL_LANGUAGE_KEY]``
    """
    attr = getattr(cls, SETTINGS_BY_MODEL_LANGUAGE_KEY, None)
    if isinstance(attr, Mapping):
        return normalize_settings_by_model_language(attr)

    model_config = getattr(cls, "model_config", None)
    if isinstance(model_config, Mapping):
        extra = model_config.get("json_schema_extra")
        if isinstance(extra, Mapping):
            tree = extra.get(SETTINGS_BY_MODEL_LANGUAGE_KEY)
            if isinstance(tree, Mapping):
                return normalize_settings_by_model_language(tree)
    return None
