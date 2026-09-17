"""Build deduped ModelServiceSwitchers from language-keyed agent models."""

from __future__ import annotations

from typing import Any, Literal

from loguru import logger

from apps.providers import AgentConfig, create_llm_service, create_stt_service, create_tts_service
from apps.runtime.services.backend import BackendClient, backend_client
from apps.runtime.services.language_switch.routes import LanguageRoute
from apps.runtime.services.language_switch.settings import build_settings_delta

ServiceKind = Literal["stt", "tts", "llm"]


def _looks_like_model_stack(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and "stt_config" in value
        and "tts_config" in value
        and "llm_config" in value
    )


def configured_languages(agent: dict[str, Any]) -> list[str]:
    """Return primary + secondary language ids in stable order."""
    language = (agent.get("config") or {}).get("language") or {}
    primary = str(language.get("primary") or "").strip()
    secondary = language.get("secondary") or []
    langs: list[str] = []
    if primary:
        langs.append(primary)
    if isinstance(secondary, list):
        for raw in secondary:
            lang = str(raw or "").strip()
            if lang and lang not in langs:
                langs.append(lang)
    return langs


def resolve_language_stacks(agent: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return ``{lang: {stt_config, tts_config, llm_config}}`` from agent config."""
    config = agent.get("config") or {}
    models = config.get("models") or {}
    if not isinstance(models, dict) or not models:
        raise ValueError("agent.config.models is missing or invalid")

    langs = configured_languages(agent)
    if _looks_like_model_stack(models):
        primary = langs[0] if langs else ""
        if not primary:
            stt = models.get("stt_config") or {}
            primary = str(stt.get("language") or "en").strip()
        if not primary:
            raise ValueError("language.primary is required to normalize flat models")
        return {
            primary: {
                "stt_config": models["stt_config"],
                "tts_config": models["tts_config"],
                "llm_config": models["llm_config"],
            }
        }

    stacks: dict[str, dict[str, Any]] = {}
    for lang in langs:
        stack = models.get(lang)
        if not isinstance(stack, dict) or not _looks_like_model_stack(stack):
            raise ValueError(f"models missing or invalid stack for language {lang!r}")
        stacks[lang] = stack
    return stacks


def _provider_id(model_cfg: dict[str, Any] | None) -> str:
    if not isinstance(model_cfg, dict):
        return ""
    return str(model_cfg.get("provider") or "").strip()


def _requires_stored_auth(provider: str) -> bool:
    from apps.runtime.services.ai_service_factory import _requires_stored_auth as check

    return check(provider)


async def merge_stack_with_auth(
    stack: dict[str, Any],
    *,
    org_id: str,
    client: BackendClient | None = None,
    auth_cache: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Merge provider auth into one language stack (``stt/tts/llm`` configs)."""
    client = client or backend_client
    cache = auth_cache if auth_cache is not None else {}
    merged: dict[str, Any] = {}

    for kind in ("stt_config", "tts_config", "llm_config"):
        blob = stack.get(kind)
        if not isinstance(blob, dict):
            raise ValueError(f"{kind} is required")
        provider = _provider_id(blob)
        if not provider:
            raise ValueError(f"{kind}.provider is required")

        if _requires_stored_auth(provider):
            if provider not in cache:
                cache[provider] = await client.get_provider_auth(provider, org_id)
            merged[kind] = {**blob, **cache[provider]}
        else:
            merged[kind] = dict(blob)
    return merged


def _pool_key(kind: ServiceKind, config: dict[str, Any]) -> tuple[str, str, str]:
    return (kind, _provider_id(config), str(config.get("model") or "").strip())


def _create_service(kind: ServiceKind, stack: dict[str, Any]) -> Any:
    agent_ai = AgentConfig.model_validate(stack)
    if kind == "stt":
        return create_stt_service(agent_ai)
    if kind == "tts":
        return create_tts_service(agent_ai)
    return create_llm_service(agent_ai)


def _build_routes_and_services(
    *,
    kind: ServiceKind,
    ordered_langs: list[str],
    stacks: dict[str, dict[str, Any]],
) -> tuple[list[Any], dict[str, LanguageRoute]]:
    config_key = f"{kind}_config"
    pool: dict[tuple[str, str, str], Any] = {}
    service_order: list[Any] = []
    routes: dict[str, LanguageRoute] = {}

    for lang in ordered_langs:
        stack = stacks[lang]
        config = stack[config_key]
        key = _pool_key(kind, config)
        if key not in pool:
            service = _create_service(kind, stack)
            pool[key] = service
            service_order.append(service)

        service = pool[key]
        delta = build_settings_delta(kind, config, service=service)
        routes[lang] = LanguageRoute(service=service, settings_delta=delta)

    return service_order, routes


def _build_switcher_for_kind(
    *,
    kind: ServiceKind,
    primary: str,
    ordered_langs: list[str],
    stacks: dict[str, dict[str, Any]],
) -> Any:
    from apps.runtime.services.language_switch.switcher import (
        ModelLLMSwitcher,
        ModelServiceSwitcher,
    )

    service_order, routes = _build_routes_and_services(
        kind=kind,
        ordered_langs=ordered_langs,
        stacks=stacks,
    )

    if kind == "llm":
        switcher = ModelLLMSwitcher(
            services=service_order,
            routes=routes,
            primary_language=primary,
        )
    else:
        switcher = ModelServiceSwitcher(
            kind=kind,
            services=service_order,
            routes=routes,
            primary_language=primary,
        )

    logger.info(
        "Built {} switcher languages={} unique_services={}",
        kind,
        ordered_langs,
        len(service_order),
    )
    return switcher


async def build_language_switchers(
    agent: dict[str, Any],
    client: BackendClient | None = None,
) -> tuple[Any, Any, Any]:
    """Return ``(stt_switcher, tts_switcher, llm_switcher)`` for the agent."""
    org_id = str(agent.get("org_id") or "").strip()
    if not org_id:
        raise ValueError("agent.org_id is required")

    raw_stacks = resolve_language_stacks(agent)
    langs = configured_languages(agent)
    primary = langs[0]
    ordered_langs = [lang for lang in langs if lang in raw_stacks]

    auth_cache: dict[str, dict[str, Any]] = {}
    stacks: dict[str, dict[str, Any]] = {}
    for lang in ordered_langs:
        stacks[lang] = await merge_stack_with_auth(
            raw_stacks[lang],
            org_id=org_id,
            client=client,
            auth_cache=auth_cache,
        )

    stt_switcher = _build_switcher_for_kind(
        kind="stt",
        primary=primary,
        ordered_langs=ordered_langs,
        stacks=stacks,
    )
    tts_switcher = _build_switcher_for_kind(
        kind="tts",
        primary=primary,
        ordered_langs=ordered_langs,
        stacks=stacks,
    )
    llm_switcher = _build_switcher_for_kind(
        kind="llm",
        primary=primary,
        ordered_langs=ordered_langs,
        stacks=stacks,
    )
    return stt_switcher, tts_switcher, llm_switcher
