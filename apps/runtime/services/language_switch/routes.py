"""Per-language routing metadata for ModelServiceSwitcher."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LanguageRoute:
    """Per-language target service and runtime settings delta."""

    service: Any
    settings_delta: Any
