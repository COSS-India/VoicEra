"""Tests for VI OBD client (config-injected, no env credentials)."""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from apps.telephony.providers.vi.config import ViConfig
from apps.telephony.providers.vi.obd.client import ViObdClient
from apps.telephony.providers.vi.obd.errors import ViObdError
from apps.telephony.providers.vi.obd.ingest import (
    build_ingestion_payload,
    ingestion_succeeded,
)
from apps.telephony.providers.vi.obd.normalize import normalize_msisdn


def _vi_config() -> ViConfig:
    return ViConfig(
        obd_username="obd-user",
        obd_password="obd-pass",
        number_flows=[
            {"phone_number": "+919876543210", "flow_id": "flow-abc=="},
        ],
    )


def test_normalize_msisdn_strips_country_code() -> None:
    assert normalize_msisdn("+919876543210") == "9876543210"
    assert normalize_msisdn("919876543210") == "9876543210"
    assert normalize_msisdn("9876543210") == "9876543210"


def test_vi_config_resolve_dial_context_variants() -> None:
    cfg = _vi_config()
    ctx = cfg.resolve_dial_context("9876543210")
    assert ctx["flow_id"] == "flow-abc=="
    assert ctx["fallback_phone"] == "+919876543210"

    ctx2 = cfg.resolve_dial_context("+919876543210")
    assert ctx2["flow_id"] == "flow-abc=="


def test_vi_config_resolve_dial_context_unknown_phone() -> None:
    cfg = _vi_config()
    with pytest.raises(ValueError, match="No VI flow_id"):
        cfg.resolve_dial_context("+919999999999")


def test_build_ingestion_payload_nested() -> None:
    payload = build_ingestion_payload("camp-key", "9876543210", "9123456789", shape="nested")
    assert payload == {
        "campaign_ID": "camp-key",
        "Records": [{"dni": "9876543210", "msisdn": "9123456789"}],
    }


def test_ingestion_succeeded() -> None:
    assert ingestion_succeeded({"data": {"status": "success"}}, 200) is True
    assert ingestion_succeeded({"data": {"rowsAffected": 1}}, 200) is True
    assert ingestion_succeeded({"data": {}}, 400) is False


def test_obd_client_requires_credentials() -> None:
    with pytest.raises(ViObdError, match="username and password"):
        ViObdClient("", "pass")


@patch("apps.telephony.providers.vi.obd.client.httpx.Client")
def test_place_single_outbound_call(mock_client_cls) -> None:
    cfg = _vi_config()
    obd = ViObdClient.from_config(cfg)

    def handler(url: str, **kwargs: object) -> httpx.Response:
        if url.endswith("/AuthToken"):
            return httpx.Response(200, json={"idToken": "token-123"})
        if url.endswith("/getActiveDNIList"):
            return httpx.Response(200, json={"dniList": ["9876543210"]})
        if url.endswith("/createCampaign"):
            return httpx.Response(
                200,
                json={
                    "status": 1,
                    "campainKey": "camp-key-1",
                    "campaign_Ref_ID": "ref-99",
                },
            )
        if url.endswith("/staticCampaignDataIngestion"):
            body = kwargs.get("json") or {}
            return httpx.Response(
                200,
                json={"data": {"status": "success", "rowsAffected": 1}, "payload": body},
            )
        return httpx.Response(404, json={"error": "not found"})

    mock_client_cls.return_value.__enter__.return_value.post.side_effect = handler

    result = obd.place_single_outbound_call(
        "+919123456789",
        agent_id="agent-1",
        flow_id="flow-abc==",
        fallback_phone="+919876543210",
    )

    assert result["status"] == "queued"
    assert result["campaign_Ref_ID"] == "ref-99"
    assert result["dni"] == "9876543210"
    assert result["flow_id"] == "flow-abc=="


def test_place_single_outbound_call_requires_flow_id() -> None:
    obd = ViObdClient.from_config(_vi_config())
    with pytest.raises(ViObdError, match="flow_id is required"):
        obd.place_single_outbound_call(
            "9876543210",
            agent_id="agent-1",
            flow_id="",
            fallback_phone="+919876543210",
        )
