"""Build the Pipecat LLM service from an Amul config."""

from __future__ import annotations

from ...registry import register_llm
from .catalog import DEFAULT_SOURCE_LANG, DEFAULT_USER_ID, resolve_base_url
from .config import AmulLLMConfig


def _require_bearer_token(cfg: AmulLLMConfig) -> str:
    token = str(cfg.bearer_token or "").strip()
    if not token:
        raise ValueError("Amul requires auth secret 'bearer_token'.")
    return token


@register_llm
def create_llm(cfg: AmulLLMConfig):
    from .llm import AmulLLMService

    return AmulLLMService(
        bearer_token=_require_bearer_token(cfg),
        base_url=resolve_base_url(),
        model=cfg.model,
        source_lang=DEFAULT_SOURCE_LANG,
        user_id=DEFAULT_USER_ID,
    )
