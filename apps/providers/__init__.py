"""Provider configuration models and service factory for voicera.

Public surface::

    from apps.providers import (
        Kind,
        AgentConfig,
        STTConfig,
        TTSConfig,
        LLMConfig,
        create_stt_service,
        create_tts_service,
        create_llm_service,
        provider_schemas,
        configuration_defaults,
    )
"""

from .base import (
    BaseLLMConfig,
    BaseLLMSettings,
    BaseProviderConfig,
    BaseSTTConfig,
    BaseTTSConfig,
    BaseTTSSettings,
    Kind,
    ProviderType,
)
from .languages import (
    LANGUAGES,
    UnknownLanguageError,
    canonical_languages,
    label,
    language_schema_extra,
    parse_language_ids,
)
from .capabilities import (
    api_capabilities,
    expand_settings,
    languages_map,
    model_ids,
    normalize_capabilities,
    settings_tree,
)
from .scoped_settings import (
    CAPABILITIES_KEY,
    SETTINGS_BY_MODEL_LANGUAGE_KEY,
    normalize_settings_by_model_language,
    resolve_settings,
    settings_schema_extra,
)
from .schema import (
    DEFAULT_SERVICE_PROVIDERS,
    UnknownProviderError,
    all_provider_auth,
    all_provider_level_auth,
    all_provider_schemas,
    configuration_defaults,
    filter_catalog_by_languages,
    list_providers,
    merge_auth_catalogs,
    provider_auth,
    provider_auth_by_id,
    provider_level_auth,
    provider_schemas,
    provider_settings,
)

# Factory imports Pipecat/loguru; load only when creating services.
_FACTORY_EXPORTS = frozenset({
    "AgentConfig",
    "LLMConfig",
    "STTConfig",
    "TTSConfig",
    "create_llm_service",
    "create_stt_service",
    "create_tts_service",
})

__all__ = [
    "Kind",
    "ProviderType",
    "LANGUAGES",
    "UnknownLanguageError",
    "UnknownProviderError",
    "canonical_languages",
    "label",
    "language_schema_extra",
    "parse_language_ids",
    "expand_settings",
    "api_capabilities",
    "languages_map",
    "model_ids",
    "normalize_capabilities",
    "settings_tree",
    "CAPABILITIES_KEY",
    "SETTINGS_BY_MODEL_LANGUAGE_KEY",
    "normalize_settings_by_model_language",
    "resolve_settings",
    "settings_schema_extra",
    "BaseProviderConfig",
    "BaseSTTConfig",
    "BaseTTSConfig",
    "BaseTTSSettings",
    "BaseLLMConfig",
    "BaseLLMSettings",
    "AgentConfig",
    "STTConfig",
    "TTSConfig",
    "LLMConfig",
    "create_stt_service",
    "create_tts_service",
    "create_llm_service",
    "DEFAULT_SERVICE_PROVIDERS",
    "provider_schemas",
    "all_provider_schemas",
    "configuration_defaults",
    "filter_catalog_by_languages",
    "list_providers",
    "provider_settings",
    "provider_auth",
    "all_provider_auth",
    "provider_auth_by_id",
    "merge_auth_catalogs",
    "provider_level_auth",
    "all_provider_level_auth",
]


def __getattr__(name: str):
    """Load factory symbols on first use so catalog dumps do not need loguru."""
    if name not in _FACTORY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .factory import (
        AgentConfig,
        LLMConfig,
        STTConfig,
        TTSConfig,
        create_llm_service,
        create_stt_service,
        create_tts_service,
    )

    mapping = {
        "AgentConfig": AgentConfig,
        "LLMConfig": LLMConfig,
        "STTConfig": STTConfig,
        "TTSConfig": TTSConfig,
        "create_llm_service": create_llm_service,
        "create_stt_service": create_stt_service,
        "create_tts_service": create_tts_service,
    }
    globals().update(mapping)
    return mapping[name]
