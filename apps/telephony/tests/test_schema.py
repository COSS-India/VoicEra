"""Tests for telephony provider schema catalog."""

from __future__ import annotations

import pytest

from apps.telephony import (
    Kind,
    PlivoClient,
    VobizClient,
    all_provider_schemas,
    configuration_telephony,
    create_client,
    provider_schemas,
)
from apps.telephony.providers.plivo.config import PlivoConfig
from apps.telephony.providers.vobiz.config import VobizConfig
from apps.telephony.schema import DEFAULT_SERVICE_PROVIDERS


def test_provider_schemas_keys():
    schemas = provider_schemas(Kind.TELEPHONY)
    assert set(schemas) == {"vobiz", "plivo"}


def test_all_provider_schemas_shape():
    schemas = all_provider_schemas()
    assert set(schemas) == {"telephony"}
    assert "vobiz" in schemas["telephony"]
    assert "plivo" in schemas["telephony"]


def test_vobiz_secrets_and_integration_models():
    schema = provider_schemas()["vobiz"]
    assert schema["provider"] == "vobiz"
    assert schema["name"] == "Vobiz"
    assert set(schema["secrets"]) == {"auth_id", "auth_token"}
    fields = schema["fields"]
    assert fields["auth_id"]["secret"] is True
    assert fields["auth_id"]["integration_model"] == "VobizAuthId"
    assert fields["auth_token"]["integration_model"] == "VobizAuthToken"
    assert "input_mode" not in fields["auth_id"]
    assert fields["base_url"]["default"] == "https://api.vobiz.ai/api/v1"
    assert fields["base_url"]["input_mode"] == "both"
    assert "kind" not in fields
    assert "provider" not in fields
    assert "name" not in fields


def test_plivo_secrets_and_integration_models():
    schema = provider_schemas()["plivo"]
    assert schema["name"] == "Plivo"
    assert set(schema["secrets"]) == {"auth_id", "auth_token"}
    fields = schema["fields"]
    assert fields["auth_id"]["integration_model"] == "PlivoAuthId"
    assert fields["auth_token"]["integration_model"] == "PlivoAuthToken"
    assert fields["base_url"]["default"] == "https://api.plivo.com/v1"


def test_catalog_omits_schema_noise():
    for provider, schema in provider_schemas().items():
        assert "$defs" not in schema, provider
        assert "$ref" not in schema, provider
        assert "properties" not in schema, provider
        assert "fields" in schema, provider
        assert "secrets" in schema, provider
        blob = str(schema)
        assert "allow_custom_input" not in blob, provider


def test_configuration_telephony_envelope():
    defaults = configuration_telephony()
    assert set(defaults["telephony"]) == {"vobiz", "plivo"}
    assert defaults["default_providers"] == DEFAULT_SERVICE_PROVIDERS
    assert DEFAULT_SERVICE_PROVIDERS["telephony"] == "vobiz"


def test_unsupported_kind():
    with pytest.raises(ValueError, match="Unsupported kind"):
        provider_schemas("stt")  # type: ignore[arg-type]


def test_create_client_from_config():
    vobiz = create_client(
        VobizConfig(auth_id="id", auth_token="tok")
    )
    assert isinstance(vobiz, VobizClient)
    assert vobiz.base_url == "https://api.vobiz.ai/api/v1"

    plivo = create_client(
        PlivoConfig(
            auth_id="id",
            auth_token="tok",
            base_url="https://api.plivo.com/v1/",
        )
    )
    assert isinstance(plivo, PlivoClient)
    assert plivo.base_url == "https://api.plivo.com/v1"


def test_list_providers_summary():
    from apps.telephony.schema import list_providers

    listed = list_providers()
    assert set(listed) == {"vobiz", "plivo"}
    assert listed["vobiz"] == {"provider": "vobiz", "name": "Vobiz"}
    assert "secrets" not in listed["vobiz"]
    assert "fields" not in listed["vobiz"]


def test_telephony_settings_and_auth_split():
    from apps.telephony.schema import UnknownProviderError, provider_auth, provider_settings

    settings = provider_settings("vobiz")
    assert set(settings["fields"]) == {"base_url"}
    assert "auth_id" not in settings["fields"]
    assert "secrets" not in settings

    auth = provider_auth("vobiz")
    assert set(auth["secrets"]) == {"auth_id", "auth_token"}
    assert set(auth["fields"]) == {"auth_id", "auth_token"}
    assert auth["fields"]["auth_id"]["integration_model"] == "VobizAuthId"

    with pytest.raises(UnknownProviderError):
        provider_auth("twilio")
