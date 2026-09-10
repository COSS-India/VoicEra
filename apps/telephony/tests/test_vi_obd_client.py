"""Unit tests for VI OBD client helpers (mocked HTTP)."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from apps.telephony.providers.vi.obd_client import (
    OBD_BASE,
    ViObdClient,
    ViObdError,
    _normalize_cpaas_base,
    get_dni_from_env,
    get_flow_id,
    normalize_msisdn,
    resolve_vi_agent_id,
    vi_env_credentials_configured,
)


def test_normalize_msisdn_strips_e164() -> None:
    assert normalize_msisdn("+919876543210") == "9876543210"
    assert normalize_msisdn("919876543210") == "9876543210"
    assert normalize_msisdn("9876543210") == "9876543210"


def test_normalize_cpaas_base_fixes_missing_cpaas() -> None:
    bad = "https://cts.myvi.in:8443/api/v1/obdcampaignapi"
    assert _normalize_cpaas_base(bad, OBD_BASE) == OBD_BASE


def test_get_dni_from_env_raises_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VI_DNI", raising=False)
    with pytest.raises(ViObdError, match="Missing VI_DNI"):
        get_dni_from_env()


def test_get_dni_from_env_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VI_DNI", "919811111111")
    assert get_dni_from_env() == "919811111111"


def test_get_flow_id_default() -> None:
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("VI_FLOW_ID", None)
        assert get_flow_id()


def test_vi_env_credentials_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VI_OBD_USERNAME", raising=False)
    monkeypatch.delenv("VI_OBD_PASSWORD", raising=False)
    assert vi_env_credentials_configured() is False
    monkeypatch.setenv("VI_OBD_USERNAME", "user")
    monkeypatch.setenv("VI_OBD_PASSWORD", "pass")
    assert vi_env_credentials_configured() is True


def test_build_ingestion_payload_nested() -> None:
    payload = ViObdClient._build_ingestion_payload(
        "abc123==", "919811111111", "919876543210", shape="nested"
    )
    assert payload == {
        "campaign_ID": "abc123==",
        "Records": [{"dni": "919811111111", "msisdn": "919876543210"}],
    }


def test_ingestion_succeeded_accepts_rows_affected() -> None:
    assert ViObdClient._ingestion_succeeded({"data": {"rowsAffected": 1}}, 200)
    assert not ViObdClient._ingestion_succeeded({"data": {"rowsAffected": 0}}, 200)


def test_upload_call_list_with_fallback_nested_succeeds() -> None:
    client = ViObdClient(username="user", password="pass")
    create_response = {"status": 1, "campainKey": "abc123==", "campaign_Ref_ID": 42}
    success_body = {"data": {"rowsAffected": 1}}

    with patch.object(
        client, "upload_call_list", return_value=(success_body, 200)
    ) as mock_upload:
        body, shape = client.upload_call_list_with_fallback(
            "token", create_response, "919811111111", "919876543210"
        )

    mock_upload.assert_called_once()
    assert shape == "nested"
    assert body["data"]["rowsAffected"] == 1


def test_resolve_vi_agent_id_path_and_custom() -> None:
    assert resolve_vi_agent_id("agent-1", {}) == "agent-1"
    assert (
        resolve_vi_agent_id(None, {"custom_parameters": {"agent_id": "a2"}}) == "a2"
    )
    assert resolve_vi_agent_id(None, {}) is None


def test_vi_client_create_application_stub() -> None:
    import asyncio

    from apps.telephony.providers.vi.client import ViClient

    async def _run() -> None:
        client = ViClient("env", "env")
        result = await client.create_application("agent-1", "https://example/vi/stream")
        assert result["status"] == "success"
        assert result["app_id"] == "vi-env"

    asyncio.run(_run())


def test_vi_list_numbers_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from apps.telephony.providers.vi.client import ViClient

    monkeypatch.setenv("VI_DNI", "9769554706")

    async def _run() -> None:
        client = ViClient("env", "env")
        result = await client.list_numbers()
        assert result["status"] == "success"
        assert result["numbers"] == ["+919769554706"]

    asyncio.run(_run())


def test_vi_list_numbers_empty_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    from apps.telephony.providers.vi.client import ViClient

    monkeypatch.delenv("VI_DNI", raising=False)

    async def _run() -> None:
        client = ViClient("env", "env")
        result = await client.list_numbers()
        assert result["numbers"] == []

    asyncio.run(_run())
