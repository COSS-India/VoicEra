"""Shared telephony clients for Vobiz and Plivo.

Public surface::

    from apps.telephony import (
        VobizClient,
        PlivoClient,
        Kind,
        provider_schemas,
        configuration_telephony,
        create_client,
        build_answer_stream_xml,
        initiate_outbound,
    )

Credentials and ``base_url`` are always injected by the caller — this package
does not look up org Integrations or Mongo.

Frame serializers require pipecat and are imported separately::

    from apps.telephony.providers.vobiz.serializers import VobizFrameSerializer
    from apps.telephony.providers.plivo.serializers import PlivoFrameSerializer
"""

from apps.telephony.base import (
    DEFAULT_POLL_ATTEMPTS,
    DEFAULT_POLL_INTERVAL_SECS,
    ApiResult,
    BaseTelephonyAuth,
    BaseTelephonyConfig,
    BaseTelephonySettings,
    Credentials,
    Kind,
)
from apps.telephony.calls import initiate_outbound
from apps.telephony.providers.plivo import PlivoClient
from apps.telephony.providers.vobiz import VobizClient
from apps.telephony.registry import (
    build_config,
    create_client,
    load_providers,
    registered_providers,
)
from apps.telephony.schema import (
    DEFAULT_SERVICE_PROVIDERS,
    UnknownProviderError,
    all_provider_auth,
    all_provider_level_auth,
    all_provider_schemas,
    configuration_telephony,
    list_providers,
    provider_auth,
    provider_level_auth,
    provider_schemas,
    provider_settings,
)
from apps.telephony.webhooks import (
    TelephonyWebhookEvent,
    decode_webhook_body,
    is_hangup_event,
    map_hangup_call_response,
    merge_webhook_payload,
    parse_stream_start,
    parse_webhook_form,
    resolve_provider_call_sid,
)
from apps.telephony.xml import build_answer_stream_xml

# Ensure vendor configs register on package import.
load_providers()

__all__ = [
    "Kind",
    "Credentials",
    "ApiResult",
    "BaseTelephonyAuth",
    "BaseTelephonySettings",
    "BaseTelephonyConfig",
    "DEFAULT_POLL_ATTEMPTS",
    "DEFAULT_POLL_INTERVAL_SECS",
    "DEFAULT_SERVICE_PROVIDERS",
    "VobizClient",
    "PlivoClient",
    "create_client",
    "build_config",
    "registered_providers",
    "load_providers",
    "provider_schemas",
    "all_provider_schemas",
    "configuration_telephony",
    "UnknownProviderError",
    "list_providers",
    "provider_settings",
    "provider_auth",
    "all_provider_auth",
    "provider_level_auth",
    "all_provider_level_auth",
    "build_answer_stream_xml",
    "initiate_outbound",
    "TelephonyWebhookEvent",
    "is_hangup_event",
    "map_hangup_call_response",
    "decode_webhook_body",
    "parse_webhook_form",
    "merge_webhook_payload",
    "parse_stream_start",
    "resolve_provider_call_sid",
]
