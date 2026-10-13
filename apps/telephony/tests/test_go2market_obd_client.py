"""Tests for Go To Market OBD dialing and helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from apps.telephony.providers.go2market.auth_helpers import (
    parse_obd_profiles,
    resolve_obd_profile,
)
from apps.telephony.providers.go2market.helpers import (
    answer_url_to_agent_wss,
    normalize_phoneno,
)
from apps.telephony.providers.go2market.obd_client import (
    Go2MarketObdClient,
    Go2MarketObdError,
)

_PROFILES = (
    '[{"serviceno":"7971504853","ukey":"ukey-test","ivrtemplateid":"193"},'
    '{"serviceno":"9876543210","ukey":"ukey-2","ivrtemplateid":"194"}]'
)


def test_normalize_phoneno() -> None:
    assert normalize_phoneno("+919379024479") == "9379024479"
    assert normalize_phoneno("919379024479") == "9379024479"


def test_parse_obd_profiles() -> None:
    pairs = parse_obd_profiles(_PROFILES)
    assert len(pairs) == 2
    assert pairs[0]["serviceno"] == "7971504853"


def test_resolve_obd_profile_by_from_number() -> None:
    profile = resolve_obd_profile(_PROFILES, "+919876543210")
    assert profile["ukey"] == "ukey-2"


def test_answer_url_to_agent_wss() -> None:
    answer = (
        "https://voice.example.com/answer?"
        "org_id=org-1&agent_id=agent-1&call_id=call-uuid"
    )
    assert answer_url_to_agent_wss(answer) == (
        "wss://voice.example.com/agent/org-1/agent-1?call_id=call-uuid"
    )


def test_obd_payload_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeResponse:
        status_code = 200
        text = '{"status":"ok","callid":"cmp-1"}'

        @staticmethod
        def json() -> dict:
            return {"status": "ok", "callid": "cmp-1"}

    def fake_post(url: str, json: dict, headers: dict) -> FakeResponse:
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, url, **kw: fake_post(url, kw["json"], kw["headers"]),
    )

    client = Go2MarketObdClient(
        "ukey-test",
        "7971504853",
        "193",
        obd_base="https://obd.voicensms.in/obd/OBDAPI/webresources",
    )
    result = client.place_single_outbound_call(
        "+919379024479",
        wss_url="wss://voice.example.com/agent/o/a?call_id=c1",
        call_id="c1",
    )

    assert captured["url"].endswith("/CreateOBDCampaignPost")
    body = captured["json"]
    assert body["ukey"] == "ukey-test"
    assert body["serviceno"] == "7971504853"
    assert body["ivrtemplateid"] == "193"
    assert body["msisdnlist"][0]["WSS"] == "wss://voice.example.com/agent/o/a?call_id=c1"
    assert body["msisdnlist"][0]["Param1"] == "wss://voice.example.com/agent/o/a?call_id=c1"
    assert result["provider_call_sid"] == "cmp-1"


def test_invalid_to_number_raises() -> None:
    client = Go2MarketObdClient(
        "ukey",
        "7971504853",
        "193",
        obd_base="https://example.com",
    )
    with pytest.raises(Go2MarketObdError, match="Invalid to_number"):
        client.place_single_outbound_call("123", wss_url="wss://x/y")


@pytest.mark.asyncio
async def test_go2market_client_initiate_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.telephony.providers.go2market.client import Go2MarketClient

    client = Go2MarketClient(
        "https://obd.voicensms.in/obd/OBDAPI/webresources",
        obd_profiles=_PROFILES,
    )

    def fake_place(*args, **kwargs):
        return {
            "status": "success",
            "message": "queued",
            "provider_call_sid": "sid-1",
            "serviceno": "9876543210",
        }

    monkeypatch.setattr(
        "apps.telephony.providers.go2market.application._obd_client",
        lambda c, from_number: MagicMock(
            place_single_outbound_call=fake_place,
        ),
    )

    result = await client.initiate_call(
        from_number="+919876543210",
        to_number="+919379024479",
        answer_url=(
            "https://voice.example.com/answer?"
            "org_id=o1&agent_id=a1&call_id=c1"
        ),
    )
    assert result["status"] == "success"
    assert result["provider_call_sid"] == "sid-1"
