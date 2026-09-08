"""Vendor capabilities: languages + settings in one catalog shape.

Each STT/TTS ``catalog.py`` declares::

    STT_CAPABILITIES = {
        "model-id": {
            "languages": {"vendor_code": "canonical_id", ...},
            "settings": {
                "vendor_code": {"voice": {...}, ...},  # no "*"
            },
        },
    }

Helpers derive model ids, language maps for ``language_schema_extra``, and a
settings tree keyed by **canonical** ids for schema dumps / UI resolve.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from .scoped_settings import normalize_settings_by_model_language

# model → { languages: {vendor: canonical}, settings: {vendor: {field: meta}} }
Capabilities = dict[str, dict[str, Any]]


def expand_settings(
    languages: Mapping[str, str],
    meta: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Copy ``meta`` under every vendor language code (no ``"*"`` in result)."""
    block = {name: dict(leaf) for name, leaf in meta.items()}
    return {vendor: copy.deepcopy(block) for vendor in languages}


def model_ids(capabilities: Mapping[str, Any]) -> tuple[str, ...]:
    """Model ids in declaration order."""
    return tuple(capabilities.keys())


def languages_map(capabilities: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    """``{model: {vendor_code: canonical_id}}`` for ``language_schema_extra``."""
    normalized = normalize_capabilities(capabilities)
    return {
        model: dict(entry["languages"])
        for model, entry in normalized.items()
    }


def settings_tree(capabilities: Mapping[str, Any]) -> dict[str, dict[str, dict]]:
    """Build schema dump tree: ``{model: {canonical: settings}}``.

    Re-keys vendor language codes to canonical ids via each model's ``languages``.
    When multiple vendors map to the same canonical, the first wins.
    """
    return {
        model: entry["settings"]
        for model, entry in api_capabilities(capabilities).items()
    }


def api_capabilities(capabilities: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """FE/API dump: ``{model: {languages, settings}}`` keyed by **canonical** ids.

    ``languages`` is ``{canonical_id: vendor_code}`` (first vendor wins).
    ``settings`` is ``{canonical_id: {field: meta}}``.
    """
    normalized = normalize_capabilities(capabilities)
    out: dict[str, dict[str, Any]] = {}
    for model, entry in normalized.items():
        vendor_to_canonical: dict[str, str] = entry["languages"]
        # Invert vendor→canonical to canonical→vendor for API consumers.
        languages: dict[str, str] = {}
        for vendor, canonical in vendor_to_canonical.items():
            languages.setdefault(canonical, vendor)

        settings: dict[str, dict] = {}
        for vendor, meta in entry["settings"].items():
            canonical = vendor_to_canonical[vendor]
            settings.setdefault(canonical, copy.deepcopy(meta))

        out[model] = {
            "languages": dict(sorted(languages.items())),
            "settings": normalize_settings_by_model_language({model: settings})[model],
        }
    return out


def normalize_capabilities(capabilities: Mapping[str, Any]) -> Capabilities:
    """Validate and deep-copy a capabilities map.

    Rules:
    - each model has ``languages`` and ``settings``
    - no ``"*"`` keys in ``settings``
    - every ``settings`` key must appear in ``languages``
    """
    if not isinstance(capabilities, Mapping):
        raise TypeError(f"capabilities must be a mapping, got {type(capabilities)!r}")

    out: Capabilities = {}
    for model, entry in capabilities.items():
        if not isinstance(model, str) or not model:
            raise ValueError(f"model key must be a non-empty str, got {model!r}")
        if not isinstance(entry, Mapping):
            raise TypeError(f"capabilities[{model!r}] must be a mapping")
        if "languages" not in entry or "settings" not in entry:
            raise ValueError(
                f"capabilities[{model!r}] must have 'languages' and 'settings'"
            )

        languages = entry["languages"]
        settings = entry["settings"]
        if not isinstance(languages, Mapping) or not languages:
            raise ValueError(
                f"capabilities[{model!r}].languages must be a non-empty mapping"
            )
        if not isinstance(settings, Mapping):
            raise TypeError(
                f"capabilities[{model!r}].settings must be a mapping"
            )

        lang_out: dict[str, str] = {}
        for vendor, canonical in languages.items():
            if not isinstance(vendor, str) or not vendor:
                raise ValueError(
                    f"vendor language code under {model!r} must be a non-empty str"
                )
            if vendor == "*":
                raise ValueError(
                    f"capabilities[{model!r}].languages must not use '*'"
                )
            if not isinstance(canonical, str) or not canonical:
                raise ValueError(
                    f"canonical id for {model!r}/{vendor!r} must be a non-empty str"
                )
            lang_out[vendor] = canonical

        settings_out: dict[str, dict[str, Any]] = {}
        for vendor, meta in settings.items():
            if vendor == "*":
                raise ValueError(
                    f"capabilities[{model!r}].settings must not use '*'; "
                    f"list vendor language codes explicitly"
                )
            if vendor not in lang_out:
                raise ValueError(
                    f"capabilities[{model!r}].settings key {vendor!r} "
                    f"is not in languages"
                )
            if not isinstance(meta, Mapping):
                raise TypeError(
                    f"settings for {model!r}/{vendor!r} must be a mapping"
                )
            settings_out[vendor] = copy.deepcopy(dict(meta))

        missing = set(lang_out) - set(settings_out)
        if missing:
            raise ValueError(
                f"capabilities[{model!r}].settings missing language keys: "
                f"{sorted(missing)}"
            )

        out[model] = {"languages": lang_out, "settings": settings_out}
    return out
