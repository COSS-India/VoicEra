"""Tests for VI auth helpers and OBD dialing."""

from __future__ import annotations

import pytest

from apps.telephony.providers.vi.auth_helpers import (
    ViAuthError,
    answer_url_to_vi_stream,
    format_dni_e164,
    list_dnis,
    normalize_msisdn,
    parse_dni_flows,
    resolve_dni_and_flow,
    resolve_vi_agent_id,
)
from apps.telephony.providers.vi.obd_client import ViObdClient, ViObdError

SAMPLE_FLOWS = '[{"dni":"919876543210","flow_id":"flow-a"},{"dni":"918811122233","flow_id":"flow-b"}]'


def test_parse_dni_flows() -> None:
    pairs = parse_dni_flows(SAMPLE_FLOWS)
    assert len(pairs) == 2
    assert pairs[0]["flow_id"] == "flow-a"


def test_list_dnis() -> None:
    assert list_dnis(SAMPLE_FLOWS) == ["+919876543210", "+918811122233"]


def test_resolve_dni_and_flow_single_ok() -> None:
    dni, flow = resolve_dni_and_flow(
        '[{"dni":"919876543210","flow_id":"flow-a"}]'
    )
    assert dni == "919876543210"
    assert flow == "flow-a"


def test_resolve_dni_and_flow_match_from_number() -> None:
    dni, flow = resolve_dni_and_flow(
        SAMPLE_FLOWS, from_number="+918811122233"
    )
    assert flow == "flow-b"
    assert normalize_msisdn(dni) == "8811122233"


def test_resolve_dni_and_flow_mismatch() -> None:
    with pytest.raises(ViAuthError, match="does not match"):
        resolve_dni_and_flow(SAMPLE_FLOWS, from_number="+911112223334")


def test_resolve_multi_requires_from_number() -> None:
    with pytest.raises(ViAuthError, match="from_number is required"):
        resolve_dni_and_flow(SAMPLE_FLOWS)


def test_format_dni_e164() -> None:
    assert format_dni_e164("919876543210") == "+919876543210"
    assert format_dni_e164("+919876543210") == "+919876543210"


def test_parse_normalizes_plus_dni() -> None:
    pairs = parse_dni_flows(
        '[{"dni":"+919876543210","flow_id":"flow-a"}]'
    )
    assert pairs[0]["dni"] == "919876543210"


def test_answer_url_to_vi_stream() -> None:
    assert (
        answer_url_to_vi_stream("https://voice.example.com/answer?org_id=1")
        == "wss://voice.example.com/vi/stream"
    )
    assert (
        answer_url_to_vi_stream("http://localhost:7860/answer")
        == "ws://localhost:7860/vi/stream"
    )


def test_resolve_vi_agent_id() -> None:
    assert resolve_vi_agent_id("path-id", {}) == "path-id"
    assert (
        resolve_vi_agent_id(None, {"custom_parameters": {"agentId": "from-custom"}})
        == "from-custom"
    )


def test_normalize_msisdn() -> None:
    assert normalize_msisdn("+919876543210") == "9876543210"
    assert normalize_msisdn("9876543210") == "9876543210"


def test_place_single_outbound_call_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ViObdClient(
        "user",
        "pass",
        dni_flows=[{"dni": "919876543210", "flow_id": "flow-a"}],
    )

    def fake_request(path: str, *, token=None, json_body=None):
        if path == "AuthToken":
            return {"idToken": "tok"}, 200
        if path == "createCampaign":
            assert json_body["flowid"] == "flow-a"
            return {"status": 1, "campainKey": "ckey", "campaign_Ref_ID": 42}, 200
        if path == "staticCampaignDataIngestion":
            return {"data": {"status": "success", "rowsAffected": 1}}, 200
        raise AssertionError(path)

    monkeypatch.setattr(client, "_request", fake_request)
    result = client.place_single_outbound_call(
        "+919911122233", from_number="+919876543210"
    )
    assert result["campaign_Ref_ID"] == 42
    assert result["campainKey"] == "ckey"
    assert result["msisdn"] == "9911122233"


def test_place_bulk_outbound_calls_mocked(monkeypatch: pytest.MonkeyPatch) -> None:
    client = ViObdClient(
        "user",
        "pass",
        dni_flows='[{"dni":"919876543210","flow_id":"flow-a"}]',
    )

    def fake_request(path: str, *, token=None, json_body=None):
        if path == "AuthToken":
            return {"idToken": "tok"}, 200
        if path == "createCampaign":
            return {"status": 1, "campainKey": "ckey", "campaign_Ref_ID": 99}, 200
        if path == "staticCampaignDataIngestion":
            assert len(json_body["Records"]) == 2
            return {"data": {"status": "success", "rowsAffected": 2}}, 200
        raise AssertionError(path)

    monkeypatch.setattr(client, "_request", fake_request)
    result = client.place_bulk_outbound_calls(
        ["+919911122233", "+919922233344"],
        from_number="919876543210",
    )
    assert result["campaign_Ref_ID"] == 99
    assert len(result["msisdns"]) == 2


def test_auth_token_failure() -> None:
    client = ViObdClient(
        "user",
        "pass",
        dni_flows=[{"dni": "91", "flow_id": "f"}],
    )

    def fake_request(path: str, *, token=None, json_body=None):
        return {"error": "nope"}, 401

    client._request = fake_request  # type: ignore[method-assign]
    with pytest.raises(ViObdError, match="AuthToken"):
        client.get_auth_token()


def test_phone_lookup_candidates_adds_india_country_code() -> None:
    from apps.telephony.providers.vi.auth_helpers import phone_lookup_candidates

    candidates = phone_lookup_candidates("9769554706")
    assert "9769554706" in candidates
    assert "+919769554706" in candidates
    assert "919769554706" in candidates
