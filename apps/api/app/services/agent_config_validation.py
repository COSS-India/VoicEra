"""Validate agent model configs: reject secrets, validate settings via providers."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from apps.providers.base import Kind, is_connection_based
from apps.providers.schema import (
    UnknownProviderError,
    _auth_field_names,
    _config_catalog,
    _config_class,
)

from app.models.schemas import AgentConfigPayload, AgentKnowledgeBase, AgentModels

KB_TOOL_LLM_PROVIDERS = frozenset({"openai", "groq", "azure_openai", "anthropic"})


class AgentConfigValidationError(ValueError):
    """Raised when agent config fails validation."""


def _forbidden_field_names(cls: type[Any]) -> set[str]:
    catalog = _config_catalog(cls)
    return _auth_field_names(cls) | set(catalog.get("secrets") or [])


def _placeholder_value(annotation: Any) -> Any:
    origin = getattr(annotation, "__origin__", None)
    if origin is list:
        return ["x"]
    args = getattr(annotation, "__args__", ())
    if args and any(
        getattr(a, "__origin__", None) is list or a is list for a in args
    ):
        # e.g. str | list[str]
        return "x"
    return "x"


def validate_persisted_model_config(kind: Kind, data: dict[str, Any]) -> dict[str, Any]:
    """Validate one STT/TTS/LLM blob and return secret-free dump."""
    if not isinstance(data, dict):
        raise AgentConfigValidationError(f"{kind.value}_config must be an object")
    provider = data.get("provider")
    if not provider or not isinstance(provider, str):
        raise AgentConfigValidationError(
            f"{kind.value}_config.provider is required"
        )

    try:
        cls = _config_class(kind, provider)
    except UnknownProviderError as exc:
        raise AgentConfigValidationError(str(exc)) from exc

    forbidden = _forbidden_field_names(cls)
    present_secrets = sorted(forbidden & set(data))
    if present_secrets:
        raise AgentConfigValidationError(
            f"{kind.value}_config must not include secret/auth fields: "
            + ", ".join(present_secrets)
        )

    payload = dict(data)
    for name in forbidden:
        field = cls.model_fields.get(name)
        if field is None or name in payload:
            continue
        if field.is_required():
            payload[name] = _placeholder_value(field.annotation)

    try:
        validated = cls.model_validate(payload)
    except ValidationError as exc:
        raise AgentConfigValidationError(
            f"Invalid {kind.value}_config: {exc.errors()}"
        ) from exc

    dumped = validated.model_dump(mode="python", exclude=forbidden)
    # Drop None-only noise; keep kind/provider/model/settings.
    return {key: value for key, value in dumped.items() if value is not None}


def _validate_connection_reference(
    llm_config: dict[str, Any],
    *,
    org_id: str | None,
) -> None:
    """A connection-based LLM must name an endpoint the organisation owns."""
    provider = str(llm_config.get("provider") or "")
    if not is_connection_based(provider):
        return

    connection_id = str(llm_config.get("connection_id") or "").strip()
    if not connection_id:
        raise AgentConfigValidationError(
            f"llm_config.connection_id is required for provider {provider!r}"
        )
    if not org_id:
        return

    from app.services import provider_connection_service

    if not provider_connection_service.connection_exists(
        org_id, connection_id, provider=provider
    ):
        raise AgentConfigValidationError(
            f"Unknown or disabled provider connection: {connection_id}"
        )


def _llm_supports_tools(
    llm_config: dict[str, Any],
    *,
    org_id: str | None,
) -> bool:
    """Whether the agent's LLM can run the knowledge-base tool.

    Vendor providers are judged by id. A connection-based provider is judged by
    the endpoint's own ``supports_tools`` flag — the id says nothing about what
    an operator pointed it at.
    """
    provider = str(llm_config.get("provider") or "").strip().lower()
    if is_connection_based(provider):
        if not org_id:
            return True
        from app.services import provider_connection_service

        return provider_connection_service.supports_tools(
            org_id, str(llm_config.get("connection_id") or "")
        )
    return provider in KB_TOOL_LLM_PROVIDERS


def _validate_knowledge_base(
    kb: AgentKnowledgeBase,
    *,
    org_id: str | None,
    llm_provider: str | None,
    supports_tools: bool,
) -> AgentKnowledgeBase:
    """Validate knowledge-base settings when enabled."""
    if not kb.enabled:
        return kb

    document_ids = [d.strip() for d in kb.document_ids if d and d.strip()]
    if not document_ids:
        raise AgentConfigValidationError(
            "knowledge_base.document_ids must be non-empty when enabled"
        )

    if kb.mode == "tool" and not supports_tools:
        raise AgentConfigValidationError(
            "knowledge_base.mode 'tool' requires an LLM that supports function "
            f"calling ({', '.join(sorted(KB_TOOL_LLM_PROVIDERS))}, or a provider "
            f"connection marked supports_tools); got {llm_provider!r}"
        )

    if org_id:
        from app.services import knowledge_service

        try:
            knowledge_service.assert_documents_ready(org_id, document_ids)
        except knowledge_service.KnowledgeDocumentNotReadyError as exc:
            raise AgentConfigValidationError(exc.message) from exc

    return kb.model_copy(update={"document_ids": document_ids})


def validate_agent_config(
    config: AgentConfigPayload,
    *,
    org_id: str | None = None,
) -> AgentConfigPayload:
    """Validate prompts/language and strip/validate model configs."""
    greeting = (config.prompts.greeting_message or "").strip()
    if not greeting:
        raise AgentConfigValidationError("prompts.greeting_message is required")

    primary = (config.language.primary or "").strip()
    if not primary:
        raise AgentConfigValidationError("language.primary is required")

    for key in config.custom_variables:
        if not isinstance(key, str) or not key.strip():
            raise AgentConfigValidationError(
                "custom_variables keys must be non-empty strings"
            )

    models = AgentModels(
        stt_config=validate_persisted_model_config(
            Kind.STT, config.models.stt_config
        ),
        tts_config=validate_persisted_model_config(
            Kind.TTS, config.models.tts_config
        ),
        llm_config=validate_persisted_model_config(
            Kind.LLM, config.models.llm_config
        ),
    )

    _validate_connection_reference(models.llm_config, org_id=org_id)

    llm_provider = str(models.llm_config.get("provider") or "")
    knowledge_base = _validate_knowledge_base(
        config.knowledge_base,
        org_id=org_id,
        llm_provider=llm_provider,
        supports_tools=_llm_supports_tools(models.llm_config, org_id=org_id),
    )

    return config.model_copy(
        update={
            "prompts": config.prompts.model_copy(
                update={"greeting_message": greeting}
            ),
            "language": config.language.model_copy(update={"primary": primary}),
            "models": models,
            "knowledge_base": knowledge_base,
        }
    )
