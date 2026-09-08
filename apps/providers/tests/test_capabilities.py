"""Tests for vendor capabilities helpers."""

from __future__ import annotations

import pytest

from apps.providers.capabilities import (
    expand_settings,
    languages_map,
    model_ids,
    normalize_capabilities,
    settings_tree,
)
from apps.providers.scoped_settings import resolve_settings


def test_expand_settings_fills_all_vendor_codes():
    languages = {"hi-IN": "hi", "en-IN": "en"}
    meta = {
        "voice": {"default": "a", "options": ["a"], "input_type": "dropdown"},
    }
    expanded = expand_settings(languages, meta)
    assert set(expanded) == {"hi-IN", "en-IN"}
    assert "*" not in expanded
    assert expanded["hi-IN"]["voice"]["default"] == "a"
    expanded["en-IN"]["voice"]["default"] = "b"
    assert expanded["hi-IN"]["voice"]["default"] == "a"


def test_normalize_rejects_star_in_settings():
    with pytest.raises(ValueError, match="must not use"):
        normalize_capabilities(
            {
                "m": {
                    "languages": {"en": "en"},
                    "settings": {"*": {}},
                }
            }
        )


def test_normalize_requires_settings_for_every_language():
    with pytest.raises(ValueError, match="missing language keys"):
        normalize_capabilities(
            {
                "m": {
                    "languages": {"en": "en", "hi": "hi"},
                    "settings": {"en": {}},
                }
            }
        )


def test_settings_tree_rekeys_to_canonical():
    caps = {
        "bulbul:v2": {
            "languages": {"hi-IN": "hi", "en-IN": "en"},
            "settings": expand_settings(
                {"hi-IN": "hi", "en-IN": "en"},
                {
                    "voice": {
                        "default": "anushka",
                        "options": ["anushka"],
                        "input_type": "both",
                        "allow_custom_input": True,
                    },
                },
            ),
        }
    }
    tree = settings_tree(caps)
    assert set(tree["bulbul:v2"]) == {"hi", "en"}
    assert resolve_settings(tree, "bulbul:v2", "hi")["voice"]["default"] == "anushka"
    assert model_ids(caps) == ("bulbul:v2",)
    assert languages_map(caps)["bulbul:v2"]["hi-IN"] == "hi"


def test_api_capabilities_uses_canonical_language_keys():
    from apps.providers.capabilities import api_capabilities

    caps = {
        "m": {
            "languages": {"hi-IN": "hi", "en-IN": "en"},
            "settings": expand_settings(
                {"hi-IN": "hi", "en-IN": "en"},
                {"voice": {"default": "a", "options": ["a"], "input_type": "dropdown"}},
            ),
        }
    }
    dumped = api_capabilities(caps)
    assert set(dumped["m"]["languages"]) == {"hi", "en"}
    assert dumped["m"]["languages"]["hi"] == "hi-IN"
    assert dumped["m"]["languages"]["en"] == "en-IN"
    assert set(dumped["m"]["settings"]) == {"hi", "en"}
    assert dumped["m"]["settings"]["hi"]["voice"]["default"] == "a"
