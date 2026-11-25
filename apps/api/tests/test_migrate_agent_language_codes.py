"""Unit tests for the od/bh → or/bhb agent language migration helper."""

from __future__ import annotations

from app.services.language_code_migration import migrate_agent_config


def test_migrate_renames_primary_secondary_and_model_keys():
    config = {
        "language": {"primary": "od", "secondary": ["bh", "hi"]},
        "models": {
            "od": {
                "stt_config": {"provider": "x", "language": "od"},
                "tts_config": {"provider": "x", "language": "od"},
                "llm_config": {"provider": "x"},
            },
            "bh": {
                "stt_config": {"provider": "x", "language": "bh"},
                "tts_config": {"provider": "x", "language": "bh"},
                "llm_config": {"provider": "x"},
            },
            "hi": {
                "stt_config": {"provider": "x", "language": "hi"},
                "tts_config": {"provider": "x", "language": "hi"},
                "llm_config": {"provider": "x"},
            },
        },
    }
    updated, changed = migrate_agent_config(config)
    assert changed is True
    assert updated["language"]["primary"] == "or"
    assert updated["language"]["secondary"] == ["bhb", "hi"]
    assert set(updated["models"]) == {"or", "bhb", "hi"}
    assert updated["models"]["or"]["stt_config"]["language"] == "or"
    assert updated["models"]["bhb"]["tts_config"]["language"] == "bhb"
    assert updated["models"]["hi"]["stt_config"]["language"] == "hi"


def test_migrate_noop_when_already_bcp47():
    config = {
        "language": {"primary": "or", "secondary": ["bhb"]},
        "models": {"or": {"stt_config": {"language": "or"}}},
    }
    updated, changed = migrate_agent_config(config)
    assert changed is False
    assert updated["language"]["primary"] == "or"
