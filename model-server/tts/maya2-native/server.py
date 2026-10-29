"""maya2-native -- the TTS slot's server.

    POST /v1/audio/speech   OpenAI's speech endpoint, streamed as it generates
    GET  /v1/voices         the 20 named voices and the languages each was trained on
    GET  /v1/models         OpenAI model list (one entry, MAYA_MODEL_NAME)
    GET  /health            503 while loading and capturing CUDA graphs, 200 once it can serve
    GET  /demo              a page that plays the stream while it is generated
    WS   /v1/tts/stream     upstream's multi-context WebSocket, unchanged

**This wraps upstream's server rather than replacing it.** `maya3.server` is an
OpenAI-compatible aiohttp server over a continuous-batching, CUDA-graphed engine:
admission control, a queue deadline, cancellation when the client hangs up, and
a failure after audio has started aborting the connection instead of ending it
cleanly. tts/rumik-oss-1 had to rebuild all of that because its upstream had a
per-token Python loop; this one does not, so the only code here is the slot
contract upstream does not follow. contract.py states those differences and is
tested without a GPU.

How it attaches, so the next upgrade knows what it depends on (pinned upstream
commit in requirements.txt):

* `Maya3Server._json` -- the one place a request body is parsed. Overridden to
  shape the speech request (contract.shape_speech_body).
* `Maya3Server.resolve_voice` -- default voice, OpenAI voice names.
* `models`, `list_voices`, `add_voice`, `delete_voice` -- the router binds these
  as `self.<name>` when `app()` runs, so overriding the method replaces the route.
* `on_response_prepare` -- stamps X-Audio-Format before headers leave, which is
  the only point that sees a streamed response's headers.

Barge-in: the caller hangs up, aiohttp cancels the handler (handler_cancellation
is on), upstream's `finally` cancels the engine request, and the seat is free on
the next 80 ms tick.
"""

from __future__ import annotations

import logging
from pathlib import Path

import contract
from aiohttp import web
from config import Config
from maya3 import server as upstream

HERE = Path(__file__).resolve().parent
DEMO_PAGE = HERE / "static" / "demo.html"

log = logging.getLogger("maya2-native")


class SlotServer(upstream.Maya3Server):
    """Upstream's server with this repo's slot contract on top."""

    def __init__(self, cfg: Config, **kw):
        super().__init__(
            max_pending=cfg.pending_limit,
            queue_deadline_ms=cfg.queue_deadline_ms,
            http_max_lag_s=cfg.http_max_lag_s,
            normalise=cfg.normalise,
            **kw,
        )
        self.cfg = cfg

    # ------------------------------------------------------------------ app
    def app(self) -> web.Application:
        app = super().app()
        app.router.add_get("/demo", self.demo)
        app.on_response_prepare.append(self._stamp)
        return app

    async def demo(self, _request: web.Request) -> web.StreamResponse:
        return web.FileResponse(DEMO_PAGE, headers={"Content-Type": "text/html; charset=utf-8"})

    # ------------------------------------------------------------------ requests
    async def _json(self, request: web.Request) -> dict:
        body = await super()._json(request)
        if request.path != contract.SPEECH_PATH:
            return body
        body, extra = contract.shape_speech_body(body, self.cfg.default_format)
        request["maya_format"] = body.get("response_format")
        request["maya_headers"] = extra
        return body

    def resolve_voice(self, voice):
        if self.tts is not None:
            voice = contract.pick_voice(voice, self.cfg.default_voice, self.engine.registry.ids())
        return super().resolve_voice(voice)

    async def _stamp(self, request: web.Request, response: web.StreamResponse) -> None:
        """Runs once per response, immediately before its headers are written."""
        if request.path != contract.SPEECH_PATH or not 200 <= response.status < 300:
            return
        fmt = contract.audio_format_header(request.get("maya_format"))
        if fmt:
            response.headers["X-Audio-Format"] = fmt
        response.headers["X-Model"] = self.cfg.model_name
        for key, value in (request.get("maya_headers") or {}).items():
            response.headers[key] = value
        voice = response.headers.get("X-Maya3-Voice")
        lang = response.headers.get("X-Maya3-Language")
        if voice and lang and self.tts is not None:
            response.headers["X-Voice"] = voice
            try:
                meta = getattr(self.engine.registry.get(voice), "meta", None)
            except KeyError:
                meta = None
            if contract.untrained_language(meta, lang):
                response.headers["X-Voice-Untrained-Language"] = lang

    # ------------------------------------------------------------------ catalogue
    async def models(self, _request: web.Request) -> web.Response:
        return web.json_response(
            {
                "object": "list",
                "data": [
                    {"id": self.cfg.model_name, "object": "model", "owned_by": "maya-research"}
                ],
            }
        )

    async def list_voices(self, _request: web.Request) -> web.Response:
        try:
            self.ready()
        except upstream.ApiError as exc:
            return exc.response()
        reg = self.engine.registry
        rows = []
        for vid in reg.ids():
            try:
                v = reg.get(vid)
            except KeyError:  # removed between ids() and get()
                continue
            mode = "named" if upstream.is_named(v) else getattr(v, "mode", None)
            rows.append((vid, mode, getattr(v, "meta", None)))
        return web.json_response(contract.voice_roster(rows, self.cfg.default_voice))

    # ------------------------------------------------------------------ cloning (off for now)
    def _cloning_refused(self) -> web.Response:
        return upstream.ApiError(
            403,
            "voice_cloning_disabled",
            "voice registration is disabled on this deployment (MAYA_VOICE_CLONING=false); "
            "use one of the named voices from GET /v1/voices",
        ).response()

    async def add_voice(self, request: web.Request) -> web.StreamResponse:
        if not self.cfg.voice_cloning:
            return self._cloning_refused()
        return await super().add_voice(request)

    async def delete_voice(self, request: web.Request) -> web.StreamResponse:
        if not self.cfg.voice_cloning:
            return self._cloning_refused()
        return await super().delete_voice(request)


def load_model(cfg: Config):
    """Weights -> a running engine with the named voices registered.

    Paths are resolved explicitly rather than through `from_pretrained(repo)`, so
    the codec and speaker encoder come from the folders fetch.sh filled, not from
    whatever a Hugging Face cache happens to hold.
    """
    from maya3 import hub
    from maya3.api import Maya3TTS

    path = Path(cfg.model_path)
    if cfg.model_path.startswith("/") and not path.is_dir():
        raise FileNotFoundError(
            f"MAYA_MODEL_PATH={cfg.model_path} does not exist in the container. Run "
            "tts/maya2-native/fetch.sh on the host before starting the slot, "
            "and check MAYA_MODELS_DIR."
        )
    # A folder that is not there falls back to upstream's resolution: the repo
    # ids in the release's maya3_config.json, from the HF cache or the network.
    # That is the path for MAYA_MODEL_PATH=<repo id> without fetch.sh.
    mimi = cfg.mimi_dir if Path(cfg.mimi_dir).is_dir() else None
    ecapa = cfg.ecapa_dir if Path(cfg.ecapa_dir).is_dir() else None
    paths = hub.resolve(cfg.model_path, mimi=mimi, ecapa=ecapa)
    log.info(
        "loading %s (backbone %s, mimi %s) max_seats=%d capacity=%d depth=%s",
        paths["ckpt"],
        paths["backbone_dir"],
        paths["mimi_dir"],
        cfg.max_seats,
        cfg.capacity,
        cfg.depth_dtype,
    )
    tts = Maya3TTS.from_pretrained(
        paths["ckpt"],
        paths["backbone_dir"],
        paths["mimi_dir"],
        ecapa_dir=paths["ecapa_dir"],
        device=cfg.device,
        voices=False,
        **cfg.engine_kwargs(),
    )
    if paths.get("voices_json"):
        named = tts.load_named_voices(paths["voices_json"])
        log.info("named voices: %s", ", ".join(named))
    try:
        tts.engine.registry.get(cfg.default_voice)
    except KeyError:
        tts.close()
        raise ValueError(
            f"MAYA_DEFAULT_VOICE={cfg.default_voice!r} is not a voice in this release; "
            f"registered: {', '.join(tts.voices)}"
        ) from None
    return tts


def create_server(cfg: Config | None = None, tts=None) -> SlotServer:
    """The server, loading in the background unless an engine is handed in (tests)."""
    cfg = cfg or Config.from_env()
    if tts is not None:
        return SlotServer(cfg, tts=tts)
    return SlotServer(cfg, loader=lambda: load_model(cfg))


def main() -> None:
    cfg = Config.from_env()
    logging.basicConfig(
        level=cfg.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    srv = create_server(cfg)
    log.info(
        "maya2-native on :%d (seats=%d pending=%d deadline=%.0f ms default voice=%s format=%s "
        "normalise=%s cloning=%s)",
        cfg.port,
        cfg.max_seats,
        cfg.pending_limit,
        cfg.queue_deadline_ms,
        cfg.default_voice,
        cfg.default_format,
        cfg.normalise,
        cfg.voice_cloning,
    )
    # handler_cancellation: a client that hangs up cancels its handler, which is
    # what frees the seat. aiohttp >= 3.7 defaults it off.
    web.run_app(
        srv.app(),
        host=cfg.host,
        port=cfg.port,
        access_log=None,
        handler_cancellation=True,
        print=None,
    )


if __name__ == "__main__":
    main()
