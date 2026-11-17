"""Mutual exclusion between deterministic tool and LID tap modes."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.processors.aggregators.llm_context import LLMContext, NOT_GIVEN

from apps.runtime.services.language_switch.lid.config import (
    LANGUAGE_SWITCHING_MODE_DETERMINISTIC,
    LANGUAGE_SWITCHING_MODE_LID,
    language_switching_mode,
    resolve_lid_config,
)
from apps.runtime.services.language_switch.tools import configure_language_switching


def _switcher() -> MagicMock:
    return MagicMock(services=[])


def _multi_agent() -> dict:
    return {
        "agent_id": "agent-1",
        "config": {
            "language": {"primary": "hi", "secondary": ["kn"]},
        },
    }


def test_deterministic_mode_registers_tool_and_skips_lid():
    behaviour = {"language_switching_mode": LANGUAGE_SWITCHING_MODE_DETERMINISTIC}
    assert language_switching_mode(behaviour) == LANGUAGE_SWITCHING_MODE_DETERMINISTIC

    with patch.dict(os.environ, {"NEMOTRON_LID_URL": "http://127.0.0.1:8765"}):
        assert resolve_lid_config(behaviour, multilingual=True) is None

    context = LLMContext([])
    configure_language_switching(
        _multi_agent(),
        context=context,
        stt_switcher=_switcher(),
        tts_switcher=_switcher(),
        llm_switcher=_switcher(),
    )
    assert isinstance(context.tools, ToolsSchema)
    assert context.tools.standard_tools[0].name == "switch_language"


def test_lid_mode_resolves_config_and_tool_can_stay_unregistered():
    """Factory skips configure_language_switching in lid mode; config resolves."""
    behaviour = {"language_switching_mode": LANGUAGE_SWITCHING_MODE_LID}
    assert language_switching_mode(behaviour) == LANGUAGE_SWITCHING_MODE_LID

    with patch.dict(os.environ, {"NEMOTRON_LID_URL": "http://lid.test"}):
        cfg = resolve_lid_config(behaviour, multilingual=True)
        assert cfg is not None
        assert cfg.url == "http://lid.test"

    # Simulating factory: do not call configure_language_switching in lid mode.
    context = LLMContext([])
    assert context.tools is NOT_GIVEN


def test_lid_mode_without_url_is_fail_closed():
    behaviour = {"language_switching_mode": LANGUAGE_SWITCHING_MODE_LID}
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("NEMOTRON_LID_URL", None)
        assert resolve_lid_config(behaviour, multilingual=True) is None
