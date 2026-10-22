"""Tests for Go To Market DID-WebSocket client and link/unlink."""

from __future__ import annotations

import httpx
import pytest

from apps.telephony.providers.go2market.did_websocket_client import (
    deactivate_did_websocket,
    did_websocket_root,
    find_mapping_for_did,
    list_did_websockets,
    replace_did_websocket,
    set_did_websocket,
    set_did_websocket_active,
    update_did_websocket,
)
from apps.telephony.providers.go2market.obd_client import Go2MarketObdError

_OBD_BASE = "https://obd.voicensms.in/obd/OBDAPI/webresources"
_PROFILES = (
    '[{"serviceno":"7971504853","ukey":"ukey-test","ivrtemplateid":"193"}]'
)


def test_did_websocket_root_from_obd_base() -> None:
    assert did_websocket_root(_OBD_BASE) == (
        "https://obd.voicensms.in/obd/api/did-websocket"
    )


def test_find_mapping_for_did_tolerant_shapes() -> None:
    body = {
        "data": [
            {"id": 1, "did": "7971504853", "websocketurl": "wss://a/x"},
            {"id": 2, "did": "+919876543210", "websocketurl": "wss://a/y"},
        ]
    }
    found = find_mapping_for_did(body, "9876543210")
    assert found is not None
    assert found["id"] == 2


def test_set_did_websocket_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeResponse:
        status_code = 200
        text = "{}"

        @staticmethod
        def json() -> dict:
            return {"status": "ok"}

    def fake_post(self, url: str, **kw):
        captured["url"] = url
        captured["json"] = kw["json"]
        return FakeResponse()

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    body = set_did_websocket(
        _OBD_BASE,
        ukey="ukey-test",
        did="+917971504853",
        websocketurl="wss://voice.example.com/agent/o1/a1",
        isactive=True,
    )
    assert body["status"] == "ok"
    assert captured["url"] == "https://obd.voicensms.in/obd/api/did-websocket"
    assert captured["json"] == {
        "ukey": "ukey-test",
        "did": "7971504853",
        "websocketurl": "wss://voice.example.com/agent/o1/a1",
        "isactive": True,
    }


def test_list_and_deactivate(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []

    class FakeResponse:
        def __init__(self, status_code: int, payload: object):
            self.status_code = status_code
            self._payload = payload
            self.text = ""

        def json(self):
            return self._payload

    def fake_get(self, url: str, **_kw):
        calls.append(("GET", url))
        return FakeResponse(
            200,
            [{"id": 9, "did": "7971504853", "websocketurl": "wss://x"}],
        )

    def fake_put(self, url: str, **kw):
        calls.append(("PUT", url))
        assert kw["json"] == {
            "ukey": "ukey-test",
            "id": 9,
            "isactive": False,
        }
        return FakeResponse(200, {"ok": True})

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    monkeypatch.setattr(httpx.Client, "put", fake_put)

    listed = list_did_websockets(_OBD_BASE, ukey="ukey-test")
    assert find_mapping_for_did(listed, "7971504853")["id"] == 9
    calls.clear()

    assert deactivate_did_websocket(
        _OBD_BASE, ukey="ukey-test", did="7971504853"
    )
    assert calls[0][0] == "GET"
    assert calls[0][1].endswith("/ukey/ukey-test")
    assert calls[1] == ("PUT", "https://obd.voicensms.in/obd/api/did-websocket/active")


def test_deactivate_missing_mapping_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status_code = 200
        text = "[]"

        @staticmethod
        def json() -> list:
            return []

    monkeypatch.setattr(
        httpx.Client,
        "get",
        lambda self, url, **kw: FakeResponse(),
    )
    assert not deactivate_did_websocket(
        _OBD_BASE, ukey="ukey-test", did="7971504853"
    )


def test_set_did_websocket_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeResponse:
        status_code = 500
        text = "boom"

        @staticmethod
        def json() -> dict:
            return {"error": "boom"}

    monkeypatch.setattr(
        httpx.Client,
        "post",
        lambda self, url, **kw: FakeResponse(),
    )
    with pytest.raises(Go2MarketObdError, match="HTTP 500"):
        set_did_websocket(
            _OBD_BASE,
            ukey="u",
            did="7971504853",
            websocketurl="wss://x",
        )


@pytest.mark.asyncio
async def test_link_number_posts_did_websocket(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.telephony.providers.go2market.client import Go2MarketClient

    captured: dict = {}

    def fake_replace(base, *, ukey, did, websocketurl):
        captured.update(
            {
                "base": base,
                "ukey": ukey,
                "did": did,
                "websocketurl": websocketurl,
            }
        )
        return {"ok": True}

    monkeypatch.setattr(
        "apps.telephony.providers.go2market.application.replace_did_websocket",
        fake_replace,
    )

    client = Go2MarketClient(_OBD_BASE, obd_profiles=_PROFILES)
    result = await client.link_number(
        "+917971504853",
        "go2market-app",
        stream_url="wss://voice.example.com/agent/org-1/agent-1",
    )
    assert result["status"] == "success"
    assert captured["did"] == "7971504853"
    assert captured["ukey"] == "ukey-test"
    assert captured["websocketurl"] == (
        "wss://voice.example.com/agent/org-1/agent-1"
    )


def test_update_did_websocket_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeResponse:
        status_code = 200
        text = "{}"

        @staticmethod
        def json() -> dict:
            return {"ok": True}

    def fake_put(self, url: str, **kw):
        captured["url"] = url
        captured["json"] = kw["json"]
        return FakeResponse()

    monkeypatch.setattr(httpx.Client, "put", fake_put)
    body = update_did_websocket(
        _OBD_BASE,
        ukey="ukey-test",
        did="+917971504853",
        websocketurl="wss://voice.example.com/agent/o/a",
    )
    assert body == {"ok": True}
    assert captured["url"] == (
        "https://obd.voicensms.in/obd/api/did-websocket/7971504853"
    )
    assert captured["json"] == {
        "ukey": "ukey-test",
        "websocketurl": "wss://voice.example.com/agent/o/a",
    }


def test_replace_did_websocket_updates_existing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    steps: list[str] = []

    def fake_list(base, *, ukey):
        steps.append(f"list:{ukey}")
        return [{"id": 4, "did": "7971504853", "websocketurl": "wss://old"}]

    def fake_update(base, *, ukey, did, websocketurl):
        steps.append(f"update:{did}:{websocketurl}")
        return {"updated": True}

    def fake_active(base, *, ukey, mapping_id, isactive):
        steps.append(f"active:{mapping_id}:{isactive}")
        return {"ok": True}

    monkeypatch.setattr(
        "apps.telephony.providers.go2market.did_websocket_client.list_did_websockets",
        fake_list,
    )
    monkeypatch.setattr(
        "apps.telephony.providers.go2market.did_websocket_client.update_did_websocket",
        fake_update,
    )
    monkeypatch.setattr(
        "apps.telephony.providers.go2market.did_websocket_client.set_did_websocket_active",
        fake_active,
    )

    body = replace_did_websocket(
        _OBD_BASE,
        ukey="ukey-test",
        did="7971504853",
        websocketurl="wss://voice.example.com/agent/o/a",
    )
    assert body == {"updated": True}
    assert steps == [
        "list:ukey-test",
        "update:7971504853:wss://voice.example.com/agent/o/a",
        "active:4:True",
    ]


def test_replace_did_websocket_creates_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    steps: list[str] = []

    monkeypatch.setattr(
        "apps.telephony.providers.go2market.did_websocket_client.list_did_websockets",
        lambda base, *, ukey: [],
    )

    def fake_set(base, *, ukey, did, websocketurl, isactive=True):
        steps.append(f"set:{did}:{isactive}")
        return {"created": True}

    monkeypatch.setattr(
        "apps.telephony.providers.go2market.did_websocket_client.set_did_websocket",
        fake_set,
    )

    body = replace_did_websocket(
        _OBD_BASE,
        ukey="ukey-test",
        did="7971504853",
        websocketurl="wss://voice.example.com/agent/o/a",
    )
    assert body == {"created": True}
    assert steps == ["set:7971504853:True"]


@pytest.mark.asyncio
async def test_link_number_requires_stream_url() -> None:
    from apps.telephony.providers.go2market.client import Go2MarketClient

    client = Go2MarketClient(_OBD_BASE, obd_profiles=_PROFILES)
    result = await client.link_number("+917971504853", "go2market-app")
    assert result["status"] == "fail"
    assert "answer_url" in result["message"]


@pytest.mark.asyncio
async def test_unlink_number_deactivates(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.telephony.providers.go2market.client import Go2MarketClient

    monkeypatch.setattr(
        "apps.telephony.providers.go2market.application.deactivate_did_websocket",
        lambda *a, **k: True,
    )
    client = Go2MarketClient(_OBD_BASE, obd_profiles=_PROFILES)
    result = await client.unlink_number("+917971504853")
    assert result["status"] == "success"
    assert result["deactivated"] is True


@pytest.mark.asyncio
async def test_unlink_number_idempotent_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.telephony.providers.go2market.client import Go2MarketClient

    monkeypatch.setattr(
        "apps.telephony.providers.go2market.application.deactivate_did_websocket",
        lambda *a, **k: False,
    )
    client = Go2MarketClient(_OBD_BASE, obd_profiles=_PROFILES)
    result = await client.unlink_number("+917971504853")
    assert result["status"] == "success"
    assert result["deactivated"] is False


def test_set_did_websocket_active_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class FakeResponse:
        status_code = 200
        text = "{}"

        @staticmethod
        def json() -> dict:
            return {}

    def fake_put(self, url: str, **kw):
        captured["url"] = url
        captured["json"] = kw["json"]
        return FakeResponse()

    monkeypatch.setattr(httpx.Client, "put", fake_put)
    set_did_websocket_active(
        _OBD_BASE, ukey="ukey-test", mapping_id=1, isactive=True
    )
    assert captured["url"].endswith("/did-websocket/active")
    assert captured["json"]["id"] == 1
    assert captured["json"]["isactive"] is True
