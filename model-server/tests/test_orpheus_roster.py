"""The Orpheus speaker roster has to match the checkpoint it is served with.

`voices.json` (v1) and `voices-v2.json` are not interchangeable: v2 adds Bhili
and a 23rd language, and the two use different style vocabularies entirely --
CONV/WIKI/NEWS/BOOK against `news`/`AIR style news`/`happy`. Serving the wrong
one is the quiet kind of wrong. `voice: "Bhima"` becomes an error, and a style
name from the other file is simply ignored, so a caller gets audio in a
default style and nothing says why.

The deployment ran v2 while compose declared v1 and only worked because .env
overrode it, which is the same defect the rest of this folder's overlay exists
to prevent: the running value was not the declared one, and a fresh install got
the other answer.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "tts" / "orpheus"
CATALOGUE = ROOT / "models.yaml"

pytestmark = pytest.mark.skipif(not FOLDER.is_dir(), reason="orpheus not in this checkout")


def declared_roster() -> str:
    env = yaml.safe_load((FOLDER / "compose.extra.yml").read_text(encoding="utf-8"))
    raw = env["services"]["tts"]["environment"]["ORPHEUS_VOICES_FILE"]
    # "${ORPHEUS_VOICES_FILE:-voices-v2.json}" -> "voices-v2.json"
    m = re.search(r":-([^}]+)\}", str(raw))
    return (m.group(1) if m else str(raw)).strip()


def test_the_declared_roster_file_exists():
    name = declared_roster()
    assert (FOLDER / name).is_file(), f"compose declares {name}, which is not in the folder"


def test_the_declared_roster_matches_the_checkpoint_in_the_catalogue():
    """models.yaml is the record of what this slot runs; the roster follows it."""
    notes = ""
    for entry in yaml.safe_load(CATALOGUE.read_text(encoding="utf-8"))["tts"]:
        if entry["id"] == "orpheus":
            notes = str(entry.get("notes", ""))
    # Matches indic-speak-preview-v2 and the released indic-speak alike. Pinning
    # the preview's exact name meant that recording the release in models.yaml
    # turned this check into a skip -- the guard disappearing at precisely the
    # moment the checkpoint changed, which is when it is worth having.
    #
    # The release is assumed to keep v2's roster: same 23 languages, same style
    # vocabulary. That is an assumption, not a verified fact -- the repo is
    # gated and its voices.md was not read. If a caller reports an unknown voice
    # or a silently ignored style, this is the first thing to check.
    if "indic-speak" not in notes:
        pytest.skip("models.yaml does not record an indic-speak checkpoint for orpheus")
    assert declared_roster() == "voices-v2.json", (
        f"models.yaml records the v2 checkpoint but compose defaults to "
        f"{declared_roster()!r}. The v1 roster has no Bhili voices and a "
        f"different style vocabulary, and nothing reports the mismatch."
    )


def test_the_two_rosters_are_genuinely_incompatible():
    """Guards the premise: if these ever converge, this file can go."""
    v1, v2 = (json.loads((FOLDER / n).read_text(encoding="utf-8"))
              for n in ("voices.json", "voices-v2.json"))

    def codes(doc):
        langs = doc["languages"]
        return {entry["code"] for entry in langs} if isinstance(langs, list) else set(langs)

    assert "bhb" in codes(v2), "v2 roster no longer carries Bhili"
    assert "bhb" not in codes(v1), "v1 roster now carries Bhili -- premise changed"
    assert not set(v1.get("styles", [])) & set(v2.get("styles", [])), (
        "the two rosters now share style names; a mismatch would no longer be silent"
    )
