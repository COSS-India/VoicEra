"""Tests for telephony registry creator maps."""

from __future__ import annotations

import pytest

from apps.telephony.registry import (
    ANSWER_XML_BUILDERS,
    CLIENT_CREATORS,
    FRAME_SERIALIZER_FACTORIES,
    TELEPHONY_CONFIGS,
    build_config,
    create_client,
    get_answer_xml_builder,
    get_client_creator,
    get_frame_serializer_factory,
    load_frame_serializers,
    load_providers,
    registered_providers,
)
from apps.telephony.providers.plivo.config import PlivoConfig
from apps.telephony.providers.vobiz.config import VobizConfig
from apps.telephony.providers.vobiz import VobizClient
from apps.telephony.providers.plivo import PlivoClient


@pytest.fixture(autouse=True)
def _ensure_providers_loaded() -> None:
    load_providers()


def test_registered_providers_include_vobiz_and_plivo() -> None:
    assert registered_providers() == frozenset({"vobiz", "plivo"})


@pytest.mark.parametrize("provider", ["vobiz", "plivo"])
def test_each_provider_has_config_client_and_xml(provider: str) -> None:
    assert provider in TELEPHONY_CONFIGS
    assert provider in CLIENT_CREATORS
    assert provider in ANSWER_XML_BUILDERS


@pytest.mark.parametrize("provider", ["vobiz", "plivo"])
def test_each_provider_has_frame_serializer_after_lazy_load(provider: str) -> None:
    load_frame_serializers()
    assert provider in FRAME_SERIALIZER_FACTORIES


def test_get_client_creator_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported telephony provider"):
        get_client_creator("twilio")


def test_get_answer_xml_builder_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported telephony provider for XML"):
        get_answer_xml_builder("twilio")


def test_get_frame_serializer_factory_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported telephony provider for serializer"):
        get_frame_serializer_factory("twilio")


def test_create_client_from_registered_creators() -> None:
    vobiz = create_client(VobizConfig(auth_id="id", auth_token="tok"))
    assert isinstance(vobiz, VobizClient)

    plivo = create_client(
        PlivoConfig(
            auth_id="id",
            auth_token="tok",
            base_url="https://api.plivo.com/v1/",
        )
    )
    assert isinstance(plivo, PlivoClient)


def test_build_config_rejects_empty_provider() -> None:
    with pytest.raises(ValueError, match="provider id is required"):
        build_config("")
