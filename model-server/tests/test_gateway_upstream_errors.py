"""What the gateway says when the model behind it is not answering.

A deployed-but-not-yet-listening upstream is the NORMAL state for the first
minutes after `up -d` -- NeMo restores a 2.4 GB checkpoint, vLLM captures CUDA
graphs -- and after every restart. `forward_http` did not guard
`client.send(...)`, so every httpx transport error left the route handler as a
bare `500 Internal Server Error` in plain text, with a traceback in the log. A
caller could not tell "still loading" from "the gateway is broken", and nothing
told it to retry.

That was the odd one out: `_probe` catches and reports, `_unavailable` returns a
shaped 503, `relay_ws` accepts-then-explains. Only the HTTP path did not.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "gateway"))

from app.config import Settings, Upstream  # noqa: E402
from app.main import create_app  # noqa: E402


def _app_pointing_at_nothing():
    """A port nothing is listening on -- what a still-loading model looks like."""
    dead = "http://127.0.0.1:1"
    return create_app(Settings(
        stt=Upstream(kind="stt", model="indic-conformer", url=dead),
        tts=Upstream(kind="tts", model="indic-parler", url=dead),
        llm=Upstream(kind="llm", model="", url=""),
    ))


@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/v1/audio/transcriptions"),
        ("post", "/v1/audio/speech"),
        ("get", "/stt/v1/languages"),
    ],
)
def test_an_unreachable_upstream_is_503_not_500(method, path):
    with TestClient(_app_pointing_at_nothing(), raise_server_exceptions=False) as c:
        kwargs = {"content": b""} if method == "post" else {}
        resp = getattr(c, method)(path, **kwargs)

    assert resp.status_code == 503, (
        f"{path} answered {resp.status_code}; a model that is still loading must "
        f"be a retryable 503, not an internal error"
    )
    body = resp.json()
    assert body["error"]["type"] == "upstream_unreachable", body
    # Tells the caller it is worth trying again, which 500 never did.
    assert resp.headers.get("Retry-After"), "no Retry-After on a transient failure"


def test_the_error_is_shaped_like_every_other_error_the_gateway_returns():
    """Same envelope as _unavailable, so one client branch handles both."""
    with TestClient(_app_pointing_at_nothing(), raise_server_exceptions=False) as c:
        body = c.get("/stt/v1/languages").json()
    assert set(body) == {"error"}
    assert {"message", "type"} <= set(body["error"])


def test_httpx_does_not_log_request_urls():
    """httpx logs the full absolute URL at INFO, query string included, and the
    realtime routes forward `ws.url.query` verbatim -- which is where an OpenAI
    Realtime client puts its key. The gateway's own logger stays at INFO; the
    library's must not, or `--no-access-log` in the Dockerfile means nothing."""
    import app.main  # noqa: F401  (import applies the logging configuration)

    assert logging.getLogger("httpx").level >= logging.WARNING, (
        "httpx is logging at INFO again: one line per proxied request, with the "
        "query string in it"
    )
