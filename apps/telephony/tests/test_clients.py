"""Unit tests for Vobiz/Plivo application and recording clients."""

from __future__ import annotations

import json
from typing import Any, Callable

import httpx
import pytest

from apps.telephony import PlivoClient, VobizClient
from apps.telephony.providers.plivo.client import client_or_fail as plivo_client_or_fail
from apps.telephony.providers.vobiz.client import client_or_fail as vobiz_client_or_fail

VOBIZ_BASE = "https://api.vobiz.ai/api/v1"
PLIVO_BASE = "https://api.plivo.com/v1"


def _json_response(data: Any, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        headers={"Content-Type": "application/json"},
        content=json.dumps(data).encode("utf-8"),
    )


def _bytes_response(content: bytes, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, content=content)


def _patch_client(monkeypatch: pytest.MonkeyPatch, handler: Callable):
    """Replace httpx.AsyncClient used by telephony.base with a mock-transport client."""

    transport = httpx.MockTransport(handler)

    class _PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("apps.telephony.base.httpx.AsyncClient", _PatchedAsyncClient)


# --- Credentials ---


def test_vobiz_client_rejects_empty_credentials():
    with pytest.raises(ValueError, match="Auth ID"):
        VobizClient("", "tok", VOBIZ_BASE)


def test_vobiz_client_or_fail_missing_creds():
    client, err = vobiz_client_or_fail(None, None, VOBIZ_BASE)
    assert client is None
    assert err is not None
    assert err["status"] == "fail"


def test_plivo_client_or_fail_missing_creds():
    client, err = plivo_client_or_fail("", "tok", PLIVO_BASE)
    assert client is None
    assert err["status"] == "fail"


# --- Vobiz application ---


@pytest.mark.anyio
async def test_vobiz_create_application(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert "/Account/authid/Application/" in str(request.url)
        assert request.headers["X-Auth-ID"] == "authid"
        body = json.loads(request.content)
        assert body["app_name"] == "agent-1"
        assert body["answer_url"] == "https://example.com/answer"
        return _json_response({"app_id": "app-123"})

    _patch_client(monkeypatch, handler)
    client = VobizClient("authid", "token", VOBIZ_BASE)
    result = await client.create_application("agent-1", "https://example.com/answer")
    assert result["status"] == "success"
    assert result["app_id"] == "app-123"


@pytest.mark.anyio
async def test_vobiz_create_application_http_error(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad request")

    _patch_client(monkeypatch, handler)
    client = VobizClient("authid", "token", VOBIZ_BASE)
    result = await client.create_application("agent-1", "https://example.com/answer")
    assert result["status"] == "fail"
    assert "bad request" in result["message"]


@pytest.mark.anyio
async def test_vobiz_delete_and_link(monkeypatch: pytest.MonkeyPatch):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        return _json_response({})

    _patch_client(monkeypatch, handler)
    client = VobizClient("authid", "token", VOBIZ_BASE)
    delete_result = await client.delete_application("app-1")
    link_result = await client.link_number("+15551234567", "app-1")
    unlink_result = await client.unlink_number("+15551234567")
    assert delete_result["status"] == "success"
    assert link_result["status"] == "success"
    assert unlink_result["status"] == "success"
    assert any("Application/app-1" in s for s in seen)
    assert any("numbers/+15551234567/application" in s for s in seen)


@pytest.mark.anyio
async def test_vobiz_list_numbers(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response(
            {"items": [{"e164": "+15551111111"}, {"e164": "+15552222222"}, {}]}
        )

    _patch_client(monkeypatch, handler)
    client = VobizClient("authid", "token", VOBIZ_BASE)
    result = await client.list_numbers()
    assert result["status"] == "success"
    assert result["numbers"] == ["+15551111111", "+15552222222"]


@pytest.mark.anyio
async def test_vobiz_update_application_name(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        body = json.loads(request.content)
        assert body == {"app_name": "renamed"}
        return _json_response({})

    _patch_client(monkeypatch, handler)
    client = VobizClient("authid", "token", VOBIZ_BASE)
    result = await client.update_application_name("app-1", "renamed")
    assert result["status"] == "success"


# --- Vobiz recording ---


@pytest.mark.anyio
async def test_vobiz_start_and_download_recording(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/Record/") and request.method == "POST":
            return _json_response({"recording_id": "rec-1"})
        if "/Recording/rec-1/" in path:
            return _json_response(
                {"recording_url": "https://cdn.example.com/rec-1.mp3"}
            )
        if "cdn.example.com" in str(request.url):
            return _bytes_response(b"ID3fake-mp3")
        return httpx.Response(404, text="not found")

    _patch_client(monkeypatch, handler)
    client = VobizClient("authid", "token", VOBIZ_BASE)
    recording_id = await client.start_call_recording("call-1", 3600)
    assert recording_id == "rec-1"
    audio = await client.wait_and_download_recording(
        "rec-1", max_attempts=2, interval_secs=0.01
    )
    assert audio == b"ID3fake-mp3"


@pytest.mark.anyio
async def test_vobiz_start_recording_failure(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    _patch_client(monkeypatch, handler)
    client = VobizClient("authid", "token", VOBIZ_BASE)
    assert await client.start_call_recording("call-1", 60) is None


# --- Plivo application ---


@pytest.mark.anyio
async def test_plivo_create_application_hangup_url(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        body = json.loads(request.content)
        assert body["answer_url"] == "https://example.com/answer"
        assert body["hangup_url"] == "https://example.com/answer"
        assert request.headers.get("authorization")  # basic auth present
        return _json_response({"app_id": "plivo-app-1"})

    _patch_client(monkeypatch, handler)
    client = PlivoClient("authid", "token", PLIVO_BASE)
    result = await client.create_application(
        "agent-1", "https://example.com/answer"
    )
    assert result["status"] == "success"
    assert result["app_id"] == "plivo-app-1"


@pytest.mark.anyio
async def test_plivo_link_unlink_and_list(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/Number/") and request.method == "GET":
            return _json_response(
                {"objects": [{"number": "15551111111"}, {"number": "15552222222"}]}
            )
        return _json_response({})

    _patch_client(monkeypatch, handler)
    client = PlivoClient("authid", "token", PLIVO_BASE)
    assert (await client.link_number("15551111111", "app-1"))["status"] == "success"
    assert (await client.unlink_number("15551111111"))["status"] == "success"
    listed = await client.list_numbers()
    assert listed["numbers"] == ["15551111111", "15552222222"]


@pytest.mark.anyio
async def test_plivo_update_application_name(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content) == {"app_name": "new-name"}
        return _json_response({})

    _patch_client(monkeypatch, handler)
    client = PlivoClient("authid", "token", PLIVO_BASE)
    result = await client.update_application_name("app-1", "new-name")
    assert result["status"] == "success"


# --- Plivo recording ---


@pytest.mark.anyio
async def test_plivo_recording_with_list_fallback(monkeypatch: pytest.MonkeyPatch):
    calls = {"list": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/Record/") and request.method == "POST":
            return _json_response({"recording_uuid": "rec-plivo"})
        if "/Recording/rec-plivo/" in path:
            return _json_response(
                {"recording_url": "https://media.plivo.com/rec.mp3"}
            )
        if path.endswith("/Recording/") and request.method == "GET":
            calls["list"] += 1
            return _json_response(
                {
                    "objects": [
                        {
                            "recording_id": "rec-from-list",
                            "recording_url": "https://media.plivo.com/list.mp3",
                        }
                    ]
                }
            )
        if "media.plivo.com" in str(request.url):
            return _bytes_response(b"plivo-audio")
        return httpx.Response(404, text="not found")

    _patch_client(monkeypatch, handler)
    client = PlivoClient("authid", "token", PLIVO_BASE)
    rid = await client.start_call_recording("call-uuid-1", 120)
    assert rid == "rec-plivo"
    audio = await client.wait_and_download_recording(
        recording_id="rec-plivo", max_attempts=2, interval_secs=0.01
    )
    assert audio == b"plivo-audio"

    audio2 = await client.wait_and_download_recording(
        recording_id=None,
        call_uuid="call-uuid-1",
        max_attempts=2,
        interval_secs=0.01,
    )
    assert audio2 == b"plivo-audio"
    assert calls["list"] >= 1


@pytest.mark.anyio
async def test_plivo_delete_application(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        return _json_response({})

    _patch_client(monkeypatch, handler)
    client = PlivoClient("authid", "token", PLIVO_BASE)
    result = await client.delete_application("app-9")
    assert result["status"] == "success"


# --- Outbound call ---


@pytest.mark.anyio
async def test_vobiz_initiate_call(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url).endswith("/Account/authid/Call/")
        assert request.headers["X-Auth-ID"] == "authid"
        body = json.loads(request.content)
        assert body == {
            "from": "+15550001111",
            "to": "+15550002222",
            "answer_url": "https://example.com/answer?agent_id=a1",
            "answer_method": "POST",
        }
        assert "hangup_url" not in body
        return _json_response({"call_uuid": "vobiz-call-1", "api_id": "x"})

    _patch_client(monkeypatch, handler)
    client = VobizClient("authid", "token", VOBIZ_BASE)
    result = await client.initiate_call(
        from_number="+15550001111",
        to_number="+15550002222",
        answer_url="https://example.com/answer?agent_id=a1",
        hangup_url="https://example.com/hangup",  # ignored by Vobiz
    )
    assert result["status"] == "success"
    assert result["call_uuid"] == "vobiz-call-1"
    assert result["raw"]["call_uuid"] == "vobiz-call-1"


@pytest.mark.anyio
async def test_plivo_initiate_call(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url).endswith("/Account/authid/Call/")
        assert request.headers.get("authorization")
        body = json.loads(request.content)
        assert body == {
            "from": "15550001111",
            "to": "15550002222",
            "answer_url": "https://example.com/answer?agent_id=a1",
            "answer_method": "POST",
            "hangup_url": "https://example.com/hangup?agent_id=a1",
            "hangup_method": "POST",
        }
        return _json_response({"request_uuid": "plivo-req-1", "message": "ok"})

    _patch_client(monkeypatch, handler)
    client = PlivoClient("authid", "token", PLIVO_BASE)
    result = await client.initiate_call(
        from_number="15550001111",
        to_number="15550002222",
        answer_url="https://example.com/answer?agent_id=a1",
        hangup_url="https://example.com/hangup?agent_id=a1",
    )
    assert result["status"] == "success"
    assert result["call_uuid"] == "plivo-req-1"
    assert result["request_uuid"] == "plivo-req-1"


@pytest.mark.anyio
async def test_initiate_outbound_dispatcher(monkeypatch: pytest.MonkeyPatch):
    from apps.telephony import initiate_outbound

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response({"call_uuid": "via-dispatch"})

    _patch_client(monkeypatch, handler)
    result = await initiate_outbound(
        "vobiz",
        auth_id="authid",
        auth_token="token",
        base_url=VOBIZ_BASE,
        from_number="+1",
        to_number="+2",
        answer_url="https://example.com/answer",
    )
    assert result["status"] == "success"
    assert result["call_uuid"] == "via-dispatch"


@pytest.mark.anyio
async def test_vobiz_initiate_call_http_error(monkeypatch: pytest.MonkeyPatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="bad number")

    _patch_client(monkeypatch, handler)
    client = VobizClient("authid", "token", VOBIZ_BASE)
    result = await client.initiate_call(
        from_number="+1",
        to_number="+2",
        answer_url="https://example.com/answer",
    )
    assert result["status"] == "fail"
    assert "bad number" in result["message"]
