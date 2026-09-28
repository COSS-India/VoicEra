"""BlueDots LLM catalog — default endpoint and model.

``DEFAULT_BASE_URL`` and ``DEFAULT_MODEL`` are placeholders until the real
BlueDots endpoint values are confirmed. Operators set ``base_url`` in
Integrations (ProviderAuth); when unset, ``resolve_base_url`` uses the catalog
default.
"""

from __future__ import annotations

DEFAULT_BASE_URL = "https://api.bluedots.example/v1"
DEFAULT_MODEL = "bluedots"

LLM_MODELS: tuple[str, ...] = (DEFAULT_MODEL,)


def resolve_base_url(override: str | None = None) -> str:
    """Return the Auth-stored URL when set, otherwise the catalog default."""
    if override and str(override).strip():
        return str(override).strip().rstrip("/")
    return DEFAULT_BASE_URL.rstrip("/")
