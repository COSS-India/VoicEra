"""Build Pipecat services from Kenpath configs."""

from __future__ import annotations

from ...registry import register_llm
from .catalog import (
    MODEL_VOICE_BHILI_URLS,
    resolve_auth_secret,
    resolve_backend,
    resolve_base_url,
    resolve_completions_path,
    resolve_languages,
)
from .config import KenpathLLMConfig


def _require_auth_pem(cfg: KenpathLLMConfig, model: str) -> str:
    """Load the catalog-mapped PEM for this model (Vistaar or Bharat prod/dev)."""
    auth_secret = resolve_auth_secret(model)
    private_key = str(getattr(cfg, auth_secret, "") or "").strip()
    if not private_key:
        raise ValueError(
            f"Kenpath model {model!r} requires auth secret {auth_secret!r} "
            "(RSA private key PEM)."
        )
    return private_key


@register_llm
def create_llm(cfg: KenpathLLMConfig):
    backend = resolve_backend(cfg.model)
    allowed = resolve_languages(cfg.model)
    if cfg.source_lang not in allowed:
        raise ValueError(
            f"Kenpath source_lang {cfg.source_lang!r} is not supported for "
            f"model {cfg.model!r}; expected one of {allowed}"
        )

    base_url = resolve_base_url(cfg.model, cfg.base_url)
    private_key = _require_auth_pem(cfg, cfg.model)

    if backend == "bharatvistaar":
        from .bharat_vistaar_llm import BharatVistaarLLMService

        return BharatVistaarLLMService(
            private_key=private_key,
            base_url=base_url,
            completions_path=resolve_completions_path(cfg.model),
            model=cfg.model,
            source_lang=cfg.source_lang,
        )

    from .llm import KenpathLLMService

    return KenpathLLMService(
        private_key=private_key,
        jwt_sub=cfg.jwt_sub,
        base_url=base_url,
        voice_bhili_url=MODEL_VOICE_BHILI_URLS.get(cfg.model, ""),
        model=cfg.model,
        source_lang=cfg.source_lang,
        target_lang=cfg.target_lang,
    )
