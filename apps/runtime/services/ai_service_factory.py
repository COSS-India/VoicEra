"""Build Pipecat STT / TTS / LLM services from API agent + ProviderAuth."""

from __future__ import annotations

from typing import Any

from loguru import logger

from apps.providers import (
    AgentConfig,
    create_llm_service,
    create_stt_service,
    create_tts_service,
)
from apps.providers.schema import provider_level_auth
from apps.runtime.services.backend import BackendClient, backend_client


class ServiceBuildError(RuntimeError):
    """Raised when agent models or auth cannot be turned into services."""


def _provider_id(model_cfg: dict[str, Any] | None) -> str:
    if not isinstance(model_cfg, dict):
        return ""
    return str(model_cfg.get("provider") or "").strip()


def _requires_stored_auth(provider: str) -> bool:
    """False for local / no-secret providers (e.g. indic_nemotron)."""
    catalog = provider_level_auth(provider)
    if catalog is None:
        return True
    return bool(catalog.get("secrets"))


async def merge_models_with_auth(
    agent: dict[str, Any],
    client: BackendClient | None = None,
) -> dict[str, Any]:
    """Return ``{stt_config, tts_config, llm_config}`` with secrets merged in."""
    client = client or backend_client
    config = agent.get("config") or {}
    models = config.get("models") or {}
    if not isinstance(models, dict):
        raise ServiceBuildError("agent.config.models is missing or invalid")

    org_id = str(agent.get("org_id") or "").strip()
    if not org_id:
        raise ServiceBuildError("agent.org_id is required")

    out: dict[str, Any] = {}
    for kind in ("stt_config", "tts_config", "llm_config"):
        blob = models.get(kind)
        if not isinstance(blob, dict):
            raise ServiceBuildError(f"agent.config.models.{kind} is required")
        provider = _provider_id(blob)
        if not provider:
            raise ServiceBuildError(f"{kind}.provider is required")
        if _requires_stored_auth(provider):
            auth = await client.get_provider_auth(provider, org_id)
            merged = {**blob, **auth}
            logger.info(
                "Merged auth into {} provider={} keys={}",
                kind,
                provider,
                sorted(auth.keys()),
            )
        else:
            merged = dict(blob)
            logger.info(
                "No stored auth needed for {} provider={}",
                kind,
                provider,
            )
        out[kind] = merged
    return out


async def build_ai_services(
    agent: dict[str, Any],
    client: BackendClient | None = None,
) -> tuple[Any, Any, Any]:
    """Return ``(stt, tts, llm)`` Pipecat services for the agent."""
    models = await merge_models_with_auth(agent, client=client)
    try:
        agent_ai = AgentConfig.model_validate(models)
    except Exception as exc:
        raise ServiceBuildError(f"Invalid AgentConfig: {exc}") from exc

    try:
        stt = create_stt_service(agent_ai)
        tts = create_tts_service(agent_ai)
        llm = create_llm_service(agent_ai)
    except Exception as exc:
        raise ServiceBuildError(f"Failed to create AI services: {exc}") from exc

    logger.info(
        "Created services stt={} tts={} llm={}",
        type(stt).__name__,
        type(tts).__name__,
        type(llm).__name__,
    )
    return stt, tts, llm
