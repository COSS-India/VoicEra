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


def configured_language_ids(config: dict[str, Any]) -> list[str]:
    """Primary first, then secondary (deduped)."""
    language = config.get("language") or {}
    primary = str(language.get("primary") or "").strip()
    secondary = language.get("secondary") or []
    if not isinstance(secondary, list):
        secondary = []
    seen: set[str] = set()
    out: list[str] = []
    for lang in [primary, *secondary]:
        cleaned = str(lang or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def resolve_language_models(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return ``{lang_id: {stt_config, tts_config, llm_config}}``.

    Prefers ``language_models``. Falls back to legacy ``models`` as the
    primary language only.
    """
    language_models = config.get("language_models")
    if isinstance(language_models, dict) and language_models:
        out: dict[str, dict[str, Any]] = {}
        for lang_id, stack in language_models.items():
            cleaned = str(lang_id or "").strip()
            if not cleaned or not isinstance(stack, dict):
                continue
            out[cleaned] = {
                "stt_config": stack.get("stt_config"),
                "tts_config": stack.get("tts_config"),
                "llm_config": stack.get("llm_config"),
            }
        if out:
            return out

    models = config.get("models") or {}
    if not isinstance(models, dict):
        raise ServiceBuildError("agent.config.models is missing or invalid")
    language = config.get("language") or {}
    primary = str(language.get("primary") or "").strip() or "_primary"
    return {
        primary: {
            "stt_config": models.get("stt_config"),
            "tts_config": models.get("tts_config"),
            "llm_config": models.get("llm_config"),
        }
    }


async def _merge_stack_with_auth(
    stack: dict[str, Any],
    *,
    org_id: str,
    client: BackendClient,
    label: str,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for kind in ("stt_config", "tts_config", "llm_config"):
        blob = stack.get(kind)
        if not isinstance(blob, dict):
            raise ServiceBuildError(f"{label}.{kind} is required")
        provider = _provider_id(blob)
        if not provider:
            raise ServiceBuildError(f"{label}.{kind}.provider is required")
        if _requires_stored_auth(provider):
            auth = await client.get_provider_auth(provider, org_id)
            merged = {**blob, **auth}
            logger.info(
                "Merged auth into {} provider={} keys={}",
                f"{label}.{kind}",
                provider,
                sorted(auth.keys()),
            )
        else:
            merged = dict(blob)
            logger.info(
                "No stored auth needed for {} provider={}",
                f"{label}.{kind}",
                provider,
            )
        out[kind] = merged
    return out


async def merge_language_models_with_auth(
    agent: dict[str, Any],
    client: BackendClient | None = None,
) -> dict[str, dict[str, Any]]:
    """Auth-merge every language stack in the agent config."""
    client = client or backend_client
    config = agent.get("config") or {}
    org_id = str(agent.get("org_id") or "").strip()
    if not org_id:
        raise ServiceBuildError("agent.org_id is required")

    language_models = resolve_language_models(config)
    if not language_models:
        raise ServiceBuildError("agent.config.language_models is empty")

    # Cache auth merges per provider so multi-language stacks that share the
    # same STT/TTS/LLM provider don't re-fetch secrets for every language.
    merged: dict[str, dict[str, Any]] = {}
    for lang_id, stack in language_models.items():
        merged[lang_id] = await _merge_stack_with_auth(
            stack,
            org_id=org_id,
            client=client,
            label=f"language_models[{lang_id!r}]",
        )
    return merged


async def merge_models_with_auth(
    agent: dict[str, Any],
    client: BackendClient | None = None,
) -> dict[str, Any]:
    """Return primary-language ``{stt_config, tts_config, llm_config}`` with secrets.

    Kept for callers that only need the active/primary stack. Prefer
    :func:`merge_language_models_with_auth` when language switching is involved.
    """
    config = agent.get("config") or {}
    language = config.get("language") or {}
    primary = str(language.get("primary") or "").strip()
    language_models = await merge_language_models_with_auth(agent, client=client)
    if primary and primary in language_models:
        return language_models[primary]
    # Fall back to the first available stack.
    if not language_models:
        raise ServiceBuildError("agent.config.language_models is empty")
    return next(iter(language_models.values()))


async def build_ai_services(
    agent: dict[str, Any],
    client: BackendClient | None = None,
    *,
    language: str | None = None,
    language_models: dict[str, dict[str, Any]] | None = None,
) -> tuple[Any, Any, Any]:
    """Return ``(stt, tts, llm)`` Pipecat services for the agent.

    When ``language`` is omitted, uses ``language.primary``.
    Pass pre-merged ``language_models`` to avoid a second auth fetch.
    """
    config = agent.get("config") or {}
    stacks = language_models or await merge_language_models_with_auth(
        agent, client=client
    )
    active = (language or "").strip() or str(
        (config.get("language") or {}).get("primary") or ""
    ).strip()
    if not active:
        raise ServiceBuildError("agent.config.language.primary is required")
    if active not in stacks:
        raise ServiceBuildError(
            f"No model configuration for language {active!r}; "
            f"configured={sorted(stacks)}"
        )

    models = stacks[active]
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
        "Created services language={} stt={} tts={} llm={}",
        active,
        type(stt).__name__,
        type(tts).__name__,
        type(llm).__name__,
    )
    return stt, tts, llm
