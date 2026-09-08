"""Tests for scoped settings trees."""

from __future__ import annotations

import pytest

from apps.providers.scoped_settings import (
    SETTINGS_BY_MODEL_LANGUAGE_KEY,
    normalize_settings_by_model_language,
    resolve_settings,
    settings_schema_extra,
)


def test_normalize_and_resolve_canonical_keys():
    tree = normalize_settings_by_model_language(
        {
            "m1": {
                "en": {
                    "voice": {
                        "default": "a",
                        "options": ["a", "b"],
                        "input_type": "dropdown",
                    },
                    "speed": {
                        "default": 1.0,
                        "minimum": 0.5,
                        "maximum": 2.0,
                        "input_type": "slider",
                    },
                },
            },
            "m2": {
                "hi": {
                    "voice": {
                        "default": "c",
                        "options": ["c"],
                        "input_type": "both",
                        "allow_custom_input": True,
                    },
                },
            },
        }
    )
    assert resolve_settings(tree, "m1", "en")["voice"]["default"] == "a"
    assert resolve_settings(tree, "m2", "hi")["voice"]["default"] == "c"
    assert resolve_settings(tree, "m2", "en") == {}
    assert resolve_settings(tree, "missing", "en") == {}


def test_normalize_rejects_unknown_leaf_key():
    with pytest.raises(ValueError, match="Unknown settings leaf key"):
        normalize_settings_by_model_language(
            {"m": {"en": {"voice": {"default": "a", "bogus": 1}}}}
        )


def test_settings_schema_extra_key():
    extra = settings_schema_extra({"m": {"en": {}}})
    assert SETTINGS_BY_MODEL_LANGUAGE_KEY in extra
    assert extra[SETTINGS_BY_MODEL_LANGUAGE_KEY] == {"m": {"en": {}}}
