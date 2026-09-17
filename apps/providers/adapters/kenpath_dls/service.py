"""Build Pipecat services from Kenpath DLS configs."""

from __future__ import annotations

from ...registry import register_llm
from .config import KenpathDlsLLMConfig


@register_llm
def create_llm(cfg: KenpathDlsLLMConfig):
    url = (cfg.url or "").strip().rstrip("/")
    if not url:
        raise ValueError("Kenpath DLS requires auth url (Vistaar base URL).")

    from .llm import KenpathDlsLLMService

    return KenpathDlsLLMService(
        base_url=url,
        model=cfg.model,
    )
