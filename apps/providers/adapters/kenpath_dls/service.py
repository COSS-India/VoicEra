"""Build Pipecat services from Kenpath DLS configs."""

from __future__ import annotations

from ...registry import register_llm
from .catalog import resolve_base_url
from .config import KenpathDlsLLMConfig


def _require_auth_pem(cfg: KenpathDlsLLMConfig) -> str:
    private_key = str(getattr(cfg, "private_key", "") or "").strip()
    if not private_key:
        raise ValueError(
            "Kenpath DLS requires auth secret 'private_key' (RSA private key PEM)."
        )
    return private_key


@register_llm
def create_llm(cfg: KenpathDlsLLMConfig):
    from .llm import KenpathDlsLLMService

    return KenpathDlsLLMService(
        private_key=_require_auth_pem(cfg),
        jwt_sub=cfg.jwt_sub,
        base_url=resolve_base_url(cfg.base_url),
        model=cfg.model,
    )
