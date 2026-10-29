"""The /{slot}/... passthrough forwards only allowlisted paths.

The app calls named routes only; the slot-prefixed passthrough exists for the
demo pages. Anything else a model serves -- /docs, /openapi.json, /metrics --
must not be reachable through the one port this stack publishes.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "gateway"))

from app.config import Settings, Upstream  # noqa: E402
from app.main import create_app  # noqa: E402
from conftest import free_port, serve  # noqa: E402
from fastapi import FastAPI, WebSocket  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

READ_PATHS = ("/health", "/v1/languages", "/v1/voices", "/v1/styles",
              "/v1/tts/stream", "/metrics", "/secret")


def stub(kind: str, hits: list):
    """An upstream that answers every path with its slot and records the hit.

    FastAPI also serves /docs and /openapi.json on it, as the real models do.
    """
    a = FastAPI()
    for path in READ_PATHS:
        def handler(path=path):
            hits.append(path)
            return {"slot": kind, "path": path}
        a.get(path)(handler)

    async def echo(ws: WebSocket):
        await ws.accept()
        await ws.send_text(f"{kind}:{await ws.receive_text()}")
        await ws.close()

    for path in ("/v1/realtime", "/v1/tts/ws", "/v1/secret_ws"):
        a.websocket(path)(echo)
    return a


@pytest.fixture(scope="module")
def upstreams():
    hits: list[str] = []
    ps, pt = free_port(), free_port()
    serve(stub("stt", hits), ps)
    serve(stub("tts", hits), pt)
    return {"stt": f"http://127.0.0.1:{ps}", "tts": f"http://127.0.0.1:{pt}", "hits": hits}


def gateway(upstreams, **overrides):
    stt = Upstream("stt", upstreams["stt"], "indic-transcribe",
                   passthrough_get=overrides.get("stt_get"),
                   passthrough_ws=overrides.get("stt_ws"))
    tts = Upstream("tts", upstreams["tts"], "orpheus",
                   passthrough_get=overrides.get("tts_get"),
                   passthrough_ws=overrides.get("tts_ws"))
    llm = Upstream("llm", "http://127.0.0.1:9", "qwen3.5-4b")
    return TestClient(create_app(Settings(stt, tts, llm)))


# ------------------------------------------------------------------ HTTP

@pytest.mark.parametrize("url", [
    "/stt/health", "/stt/v1/languages",
    "/tts/health", "/tts/v1/languages", "/tts/v1/voices", "/tts/v1/styles",
    "/tts/v1/tts/stream",
])
def test_the_routes_the_demo_pages_use_still_pass_through(upstreams, url):
    slot, _, rest = url.lstrip("/").partition("/")
    with gateway(upstreams) as c:
        r = c.get(url)
    assert r.status_code == 200, f"{url} -> {r.status_code}"
    assert r.json() == {"slot": slot, "path": "/" + rest}


@pytest.mark.parametrize("url", [
    "/stt/docs", "/stt/openapi.json", "/stt/redoc", "/stt/metrics",
    "/tts/docs", "/tts/openapi.json", "/tts/metrics", "/tts/secret",
    "/stt/v1/voices",                 # allowed on tts, not on stt
    "/stt/v1/languages/",             # exact match only
    "/llm/v1/models",                 # llm forwards nothing by default
])
def test_everything_else_is_a_404_that_never_reaches_the_model(upstreams, url):
    upstreams["hits"].clear()
    with gateway(upstreams) as c:
        r = c.get(url)
    assert r.status_code == 404, f"{url} -> {r.status_code}"
    assert r.json()["error"]["type"] == "not_found"
    assert upstreams["hits"] == [], f"{url} reached the upstream"


def test_the_query_string_still_reaches_an_allowed_route(upstreams):
    with gateway(upstreams) as c:
        r = c.get("/tts/v1/tts/stream?text=hello&voice=a")
    assert r.status_code == 200


def test_an_override_replaces_the_default(upstreams):
    with gateway(upstreams, tts_get=("/health",)) as c:
        assert c.get("/tts/health").status_code == 200
        assert c.get("/tts/v1/voices").status_code == 404


def test_named_routes_are_not_affected(upstreams):
    """The app's own routes do not go through the passthrough at all."""
    with gateway(upstreams, stt_get=(), tts_get=()) as c:
        assert c.get("/v1/models").status_code == 200
        assert c.get("/v1/languages").json() == {"slot": "stt", "path": "/v1/languages"}


# ------------------------------------------------------------- WebSocket

@pytest.mark.parametrize("url,slot", [("/stt/v1/realtime", "stt"), ("/tts/v1/tts/ws", "tts")])
def test_allowed_sockets_still_relay(upstreams, url, slot):
    with gateway(upstreams) as c, c.websocket_connect(url) as ws:
        ws.send_text("hi")
        assert ws.receive_text() == f"{slot}:hi"


@pytest.mark.parametrize("url", ["/stt/v1/secret_ws", "/tts/v1/realtime", "/llm/v1/realtime"])
def test_other_sockets_are_refused_with_1008(upstreams, url):
    with gateway(upstreams) as c, c.websocket_connect(url) as ws:
        frame = ws.receive_json()
        assert frame["type"] == "error"
        assert frame["reason"] == "not_exposed"
        with pytest.raises(WebSocketDisconnect) as closed:
            ws.receive_text()
        assert closed.value.code == 1008


# ------------------------------------------------------------ configuration

def test_defaults_when_nothing_is_set(monkeypatch):
    for kind in ("STT", "TTS", "LLM"):
        monkeypatch.delenv(f"{kind}_PASSTHROUGH_GET", raising=False)
        monkeypatch.delenv(f"{kind}_PASSTHROUGH_WS", raising=False)
    s = Settings.from_env()
    assert s.stt.exposes("/v1/languages") and not s.stt.exposes("/docs")
    assert s.tts.exposes("/v1/tts/ws", websocket=True)
    assert not s.llm.exposes("/health")


def test_env_lists_are_parsed_and_none_forwards_nothing(monkeypatch):
    monkeypatch.setenv("TTS_PASSTHROUGH_GET", " health , /v1/voices/ ,")
    monkeypatch.setenv("STT_PASSTHROUGH_WS", "none")
    s = Settings.from_env()
    assert s.tts.passthrough_get == ("/health", "/v1/voices")
    assert s.stt.passthrough_ws == ()
    assert not s.stt.exposes("/v1/realtime", websocket=True)
