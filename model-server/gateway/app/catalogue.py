"""The model catalogue, read from models.yaml.

One place describes every model the server can host, served at /models. The
frontend still ships its own stt.json and tts.json; until it reads this instead,
the two can disagree.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("gateway")

def _find_catalogue() -> Path:
    """Where models.yaml is, in both the ways this gateway gets run.

    The Dockerfile copies it next to the app, so in an image it sits beside this
    module. Run straight from a checkout -- which is what model-server/run/ does
    -- and that copy does not exist, only the one at the model-server root.

    Checking both is what removes the need for the symlink that used to bridge
    them. A committed symlink survives a Linux checkout and becomes a text file
    containing its own target on Windows, where it then parses as a YAML string
    and takes the loader down with it.
    """
    here = Path(__file__).resolve().parent
    for candidate in (here / "models.yaml",            # inside the image
                      here.parent.parent / "models.yaml"):  # from a checkout
        if candidate.is_file():
            return candidate
    return here / "models.yaml"


CATALOGUE_PATH = _find_catalogue()

KINDS = ("stt", "tts", "llm")


def load(path: Path | None = None) -> list[dict[str, Any]]:
    """Flatten models.yaml into one list, each entry carrying its kind.

    A missing or unreadable catalogue is not fatal -- the gateway still routes
    traffic; it just cannot describe what it is routing to.
    """
    src = path or CATALOGUE_PATH
    try:
        raw = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        log.warning("catalogue unavailable (%s): %s", src, exc)
        return []

    # Valid YAML that is not a mapping -- a bare string, a list, a number. The
    # docstring above promises an unreadable catalogue is survivable, and
    # `raw.get` on a str raises AttributeError, which the except clause above
    # does not catch. That turned /models into a 500 rather than an empty list.
    if not isinstance(raw, dict):
        log.warning("catalogue at %s is %s, not a mapping of kinds",
                    src, type(raw).__name__)
        return []

    models: list[dict[str, Any]] = []
    for kind in KINDS:
        for entry in raw.get(kind) or []:
            models.append({"kind": kind, **entry})
    return models
