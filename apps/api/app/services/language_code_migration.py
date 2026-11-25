"""Rewrite legacy VoicEra language ids to BCP 47 (od → or, bh → bhb)."""

from __future__ import annotations

import copy
from typing import Any

LANGUAGE_RENAMES: dict[str, str] = {
    "od": "or",
    "bh": "bhb",
}


def _rename_id(value: Any) -> tuple[Any, bool]:
    if not isinstance(value, str):
        return value, False
    key = value.strip()
    if key in LANGUAGE_RENAMES:
        return LANGUAGE_RENAMES[key], True
    return value, False


def _rename_language_list(values: Any) -> tuple[list[Any], bool]:
    if not isinstance(values, list):
        return [], False
    changed = False
    out: list[Any] = []
    seen: set[str] = set()
    for item in values:
        renamed, did = _rename_id(item)
        changed = changed or did
        if isinstance(renamed, str):
            cleaned = renamed.strip()
            if cleaned and cleaned not in seen:
                out.append(cleaned)
                seen.add(cleaned)
        elif renamed is not None:
            out.append(renamed)
    return out, changed


def _rename_model_stack(stack: Any) -> tuple[Any, bool]:
    if not isinstance(stack, dict):
        return stack, False
    changed = False
    out = copy.deepcopy(stack)
    for blob_key in ("stt_config", "tts_config", "llm_config"):
        blob = out.get(blob_key)
        if not isinstance(blob, dict) or "language" not in blob:
            continue
        renamed, did = _rename_id(blob.get("language"))
        if did:
            blob["language"] = renamed
            changed = True
    return out, changed


def _rename_models_map(models: Any) -> tuple[dict[str, Any], bool]:
    if not isinstance(models, dict):
        return {}, False
    changed = False
    out: dict[str, Any] = {}
    for key, stack in models.items():
        new_key, key_changed = _rename_id(key)
        new_stack, stack_changed = _rename_model_stack(stack)
        changed = changed or key_changed or stack_changed
        key_str = str(new_key).strip() if new_key is not None else ""
        if not key_str:
            continue
        if key_str in out and key_changed:
            out[key_str] = new_stack
        else:
            out.setdefault(key_str, new_stack)
    return out, changed


def migrate_agent_config(config: Any) -> tuple[dict[str, Any], bool]:
    """Return an updated agent ``config`` dict and whether anything changed."""
    if not isinstance(config, dict):
        return {}, False
    out = copy.deepcopy(config)
    changed = False

    language = out.get("language")
    if isinstance(language, dict):
        primary, did_primary = _rename_id(language.get("primary"))
        secondary, did_secondary = _rename_language_list(language.get("secondary") or [])
        if did_primary or did_secondary:
            language["primary"] = primary
            language["secondary"] = secondary
            changed = True

    models, did_models = _rename_models_map(out.get("models"))
    if did_models:
        out["models"] = models
        changed = True

    language_models, did_lm = _rename_models_map(out.get("language_models"))
    if did_lm:
        out["language_models"] = language_models
        changed = True

    return out, changed
