"""VoicEra model-server gateway.

The single published port. Routes on modality, streams everything, and holds no
model-specific knowledge -- each model server speaks OpenAI spec natively, so
adding a model never touches this file.

Settings live on the app instance rather than as a module global. That is not
ceremony: two gateways with different configurations have to be able to exist in
one process, or tests end up reassigning a shared global and whichever ran last
silently reconfigures the other one's routes.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import catalogue
from .config import Settings, Upstream
from .config import settings as env_settings
from .proxy import forward_http, make_client, relay_ws

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
# httpx logs one line per request at INFO, including the FULL absolute URL --
# query string and all. Setting the root logger to INFO therefore switched
# per-request access logging back on, undoing the Dockerfile's deliberate
# `--no-access-log`, and the WebSocket routes forward `ws.url.query` verbatim,
# which is exactly where an OpenAI Realtime client puts its key:
#
#   INFO HTTP Request: GET http://stt:8001/v1/languages?api_key=sk-... "200 OK"
#
# The gateway's own logger stays at INFO; the library's does not.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("gateway")


def conf(request: Request) -> Settings:
    return request.app.state.settings


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http = make_client()
    for up in app.state.settings.all():
        log.info(
            "%s: %s", up.kind,
            f"{up.model or '?'} -> {up.url}" if up.enabled else "not deployed",
        )
    yield
    await app.state.http.aclose()


def _unavailable(up: Upstream) -> JSONResponse:
    return JSONResponse(
        status_code=503,
        content={
            "error": {
                "message": (
                    f"No {up.kind.upper()} model is deployed. Set {up.kind.upper()}_MODEL "
                    f"in .env and include {up.kind} in COMPOSE_PROFILES."
                ),
                "type": "upstream_not_configured",
            }
        },
    )


async def _probe(client: httpx.AsyncClient, up: Upstream) -> dict:
    """Health-check an upstream. All three speak HTTP."""
    if not up.enabled:
        return {"deployed": False}
    base = {"deployed": True, "model": up.model}
    try:
        r = await client.get(f"{up.url}/health", timeout=2.0)
        return {**base, "reachable": r.status_code < 500}
    except Exception as exc:                                        # noqa: BLE001
        return {**base, "reachable": False, "error": str(exc)}


async def _rest(request: Request, up: Upstream, path: str):
    """Every REST route is the same shape: refuse if the slot is empty, else
    stream through. Kept as one helper so adding a route stays a one-liner."""
    if not up.enabled:
        return _unavailable(up)
    return await forward_http(request.app.state.http, request, f"{up.url}{path}")


def _slot(request: Request, kind: str) -> Upstream:
    """The upstream filling a named slot, or a 404 for a name that is not one."""
    slots = {up.kind: up for up in conf(request).all()}
    if kind not in slots:
        raise HTTPException(404, f"no such slot {kind!r}; expected one of "
                                 f"{', '.join(sorted(slots))}")
    return slots[kind]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a gateway bound to one configuration."""
    app = FastAPI(title="VoicEra model-server", lifespan=lifespan)
    app.state.settings = settings or env_settings

    # ------------------------------------------------------ health / catalogue

    @app.get("/health")
    async def health(request: Request):
        client: httpx.AsyncClient = request.app.state.http
        slots = conf(request).all()
        results = await asyncio.gather(*(_probe(client, up) for up in slots))
        checks = dict(zip((up.kind for up in slots), results, strict=True))
        # A slot nobody deployed is not a fault. Reporting it as degraded would
        # make every monitor cry wolf on a stack running exactly as configured.
        degraded = any(c.get("deployed") and not c.get("reachable") for c in checks.values())
        return JSONResponse(
            status_code=503 if degraded else 200,
            content={"status": "degraded" if degraded else "healthy", "upstreams": checks},
        )

    @app.get("/models")
    async def models(request: Request):
        """Everything the server can host, and which slot each model fills now.

        Distinct from /v1/models on purpose: that one is the OpenAI-compatible
        list of models you can call right now, so it must not advertise anything
        a client would get a 503 from.
        """
        live = {up.kind: up.model for up in conf(request).all() if up.enabled}
        entries = [{**m, "deployed": live.get(m["kind"]) == m["id"]} for m in catalogue.load()]
        return {
            "object": "list",
            "data": entries,
            "deployed": {kind: live.get(kind) for kind in catalogue.KINDS},
        }

    @app.get("/v1/models")
    async def list_models(request: Request):
        """OpenAI-compatible: only models that can be called right now.

        See /models for the full catalogue including what is not deployed."""
        return {
            "object": "list",
            "data": [
                {"id": up.model, "object": "model", "owned_by": "voicera", "kind": up.kind}
                for up in conf(request).all() if up.enabled and up.model
            ],
        }

    # ------------------------------------------------------ the three modalities

    # ---- demo pages ------------------------------------------------------
    #
    # Each model ships its own page and serves it at /demo on its own port. The
    # gateway only forwards, one path per slot, because two slots cannot both
    # own /demo -- STT had it first and TTS wanting it too is what forced this.
    #
    # /demo itself stays useful: with one slot filled it redirects there, so a
    # bookmark or a tunnel URL made when only STT existed keeps working, and
    # with several it lists them.

    @app.get("/demo/{slot}")
    async def slot_demo(slot: str, request: Request):
        """The demo page from whichever model fills this slot.

        The path is the model's, not ours: a folder vendored from upstream may
        serve its page at the root. See Upstream.demo_path.
        """
        up = _slot(request, slot)
        return await _rest(request, up, up.demo_path)

    @app.get("/demo", response_class=HTMLResponse)
    async def demo_index(request: Request):
        live = [up for up in conf(request).all() if up.enabled]
        if len(live) == 1:
            return RedirectResponse(f"/demo/{live[0].kind}", status_code=307)
        if not live:
            return HTMLResponse(
                "<h1>No model is deployed</h1><p>Set STT_MODEL, TTS_MODEL or "
                "LLM_MODEL in .env and include the slot in COMPOSE_PROFILES.</p>",
                status_code=503)
        items = "".join(
            f'<li><a href="/demo/{up.kind}">{up.kind.upper()} &mdash; {up.model}</a></li>'
            for up in live)
        return HTMLResponse(
            f"<h1>model-server demos</h1><ul>{items}</ul>")

    # ---- per-slot catalogue ----------------------------------------------
    #
    # STT and TTS both publish /v1/languages, and they answer with different
    # shapes -- a list of codes against a voice roster. One path cannot mean
    # both, and which one it happened to mean would depend on what was deployed.
    # So every catalogue route is reachable under its slot, and a demo page asks
    # for its own slot explicitly.
    #
    # Unprefixed /v1/languages stays pointed at STT: it is already in use, and
    # breaking it to tidy the naming would be a poor trade.

    @app.get("/v1/languages")
    async def stt_languages_compat(request: Request):
        """Kept for callers written before the slot prefixes existed."""
        return await _rest(request, conf(request).stt, "/v1/languages")

    @app.post("/v1/audio/transcriptions")
    async def transcriptions(request: Request):
        return await _rest(request, conf(request).stt, "/v1/audio/transcriptions")

    @app.websocket("/v1/asr/ws")
    async def asr_stream(ws: WebSocket):
        """Live transcription, for STT models that offer it.

        Not an OpenAI route -- OpenAI's realtime transcription is a different and
        much larger protocol, and claiming its path while speaking something else
        would be worse than an honest name of our own. The relay is transparent,
        so the protocol is entirely between the client and whichever model is
        loaded; a model that does not stream simply has nothing listening here.
        """
        up = ws.app.state.settings.stt
        if not up.enabled:
            await ws.accept()
            await ws.send_json({
                "type": "error", "reason": "upstream_not_configured",
                "error": "No STT model is deployed. Set STT_MODEL in .env and "
                         "include stt in COMPOSE_PROFILES.",
            })
            await ws.close(code=1013, reason="no STT model deployed")
            return
        target = up.url.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
        query = ws.url.query
        await relay_ws(ws, f"{target}/v1/asr/ws" + (f"?{query}" if query else ""))

    @app.websocket("/v1/realtime")
    async def realtime_transcription(ws: WebSocket):
        """OpenAI Realtime transcription relay to the STT upstream."""
        up = ws.app.state.settings.stt
        if not up.enabled:
            await ws.accept()
            await ws.send_json({
                "type": "error", "reason": "upstream_not_configured",
                "error": "No STT model is deployed. Set STT_MODEL in .env and "
                         "include stt in COMPOSE_PROFILES.",
            })
            await ws.close(code=1013, reason="no STT model deployed")
            return
        target = up.url.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
        query = ws.url.query
        await relay_ws(ws, f"{target}/v1/realtime" + (f"?{query}" if query else ""))

    @app.post("/v1/audio/speech")
    async def speech(request: Request):
        return await _rest(request, conf(request).tts, "/v1/audio/speech")

    @app.post("/v1/chat/completions")
    async def chat_completions(request: Request):
        """Passthrough to any OpenAI-compatible upstream. vLLM speaks this spec
        natively, so filling the LLM slot is a folder and an env var, not code."""
        return await _rest(request, conf(request).llm, "/v1/chat/completions")

    # ---- assets a vendored demo page loads from the site root --------------
    #
    # Declared per slot rather than guessed, and registered before the catch-all
    # so `/static/x.js` is not parsed as slot "static".
    #
    # Two slots claiming one prefix is a configuration error worth refusing:
    # whichever registered first would silently win, and the other slot's page
    # would load the wrong file rather than no file.
    def asset_handler(kind: str, prefix: str):
        """One handler per (slot, prefix). Both are captured as arguments --
        closing over the loop variables instead would give every route the last
        pair the loop happened to see."""
        async def serve_asset(path: str, request: Request):
            return await _rest(request, _slot(request, kind), f"{prefix}/{path}")
        return serve_asset

    claimed: dict[str, str] = {}
    for up in app.state.settings.all():
        for prefix in up.demo_assets:
            if prefix in claimed:
                raise RuntimeError(
                    f"both the {claimed[prefix]} and {up.kind} slots declare "
                    f"{prefix!r} as a demo asset prefix; only one slot can own a "
                    f"root path"
                )
            claimed[prefix] = up.kind
            app.add_api_route(
                f"{prefix}/{{path:path}}",
                asset_handler(up.kind, prefix),
                methods=["GET"],
            )

    @app.get("/{slot}/{path:path}")
    async def slot_passthrough(slot: str, path: str, request: Request):
        """Everything a model publishes for reading, reachable under its slot.

        A catch-all rather than a route per catalogue endpoint, because the
        alternative is editing the gateway every time a model gains one -- and
        the gateway is supposed to hold no model-specific knowledge. Declared
        last, so every named route above still wins.

        **GET only, deliberately.** The models publish mutating routes as well --
        indic-transcribe has /admin/batcher and /admin/reset_stats -- and a
        method-agnostic catch-all would put them on the one port this stack
        publishes. The synthesis routes that need a body already have named
        entries above; nothing else needs to be reachable this way.
        """
        up = _slot(request, slot)
        return await _rest(request, up, "/" + path)

    @app.websocket("/{slot}/{path:path}")
    async def slot_ws_passthrough(slot: str, path: str, ws: WebSocket):
        """The same, for sockets: /tts/v1/tts/ws, /stt/v1/realtime.

        Declared after the named socket routes, so /v1/realtime keeps its own
        handler and its own error frame.
        """
        slots = {up.kind: up for up in ws.app.state.settings.all()}
        up = slots.get(slot)
        if up is None or not up.enabled:
            await ws.accept()
            await ws.send_json({
                "type": "error", "reason": "upstream_not_configured",
                "error": f"No model is deployed in the {slot} slot.",
            })
            await ws.close(code=1013, reason=f"no {slot} model deployed")
            return
        target = up.url.replace("http://", "ws://", 1).replace("https://", "wss://", 1)
        query = ws.url.query
        await relay_ws(ws, f"{target}/{path}" + (f"?{query}" if query else ""))

    return app


# What the container runs: `uvicorn app.main:app`.
app = create_app()
