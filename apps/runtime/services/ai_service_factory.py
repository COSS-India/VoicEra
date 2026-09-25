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
from apps.runtime.services.language_switch.pool import (
    build_language_switchers,
    merge_stack_with_auth,
    resolve_language_stacks,
)
from apps.runtime.services.language_switch.switcher import (
    ModelLLMSwitcher,
    ModelServiceSwitcher,
)


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
    """Return primary-language ``{stt_config, tts_config, llm_config}`` with secrets merged."""
    client = client or backend_client
    try:
        stacks = resolve_language_stacks(agent)
    except ValueError as exc:
        raise ServiceBuildError(str(exc)) from exc

    org_id = str(agent.get("org_id") or "").strip()
    if not org_id:
        raise ServiceBuildError("agent.org_id is required")

    language = (agent.get("config") or {}).get("language") or {}
    primary = str(language.get("primary") or "").strip()
    if not primary:
        primary = next(iter(stacks.keys()), "")
    if not primary or primary not in stacks:
        raise ServiceBuildError("agent.config.language.primary is required")

    try:
        return await merge_stack_with_auth(
            stacks[primary],
            org_id=org_id,
            client=client,
        )
    except ValueError as exc:
        raise ServiceBuildError(str(exc)) from exc


async def build_ai_services(
    agent: dict[str, Any],
    client: BackendClient | None = None,
    *,
    caller_phone: str | None = None,
) -> tuple[ModelServiceSwitcher, ModelServiceSwitcher, ModelLLMSwitcher]:
    """Return ``(stt_switcher, tts_switcher, llm_switcher)`` for the agent.

    ``caller_phone`` is per-call context for an LLM whose endpoint wants it;
    configs that do not declare the field ignore it.
    """
    try:
        return await build_language_switchers(
            agent, client=client, caller_phone=caller_phone
        )
    except ValueError as exc:
        raise ServiceBuildError(str(exc)) from exc


async def build_legacy_ai_services(
    agent: dict[str, Any],
    client: BackendClient | None = None,
    *,
    caller_phone: str | None = None,
) -> tuple[Any, Any, Any]:
    """Return bare ``(stt, tts, llm)`` for the agent primary language stack."""
    models = await merge_models_with_auth(agent, client=client)
    if caller_phone:
        models["llm_config"]["caller_phone"] = caller_phone
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
