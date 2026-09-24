"""rumik-oss-1 on the OpenAI speech endpoint.

    POST /v1/audio/speech    OpenAI-compatible; streams while generating
    GET  /health             503 until the checkpoint and codec are loaded
    GET  /v1/voices          the speaker roster, for building agent config
    GET  /v1/models          OpenAI-compatible single-model list
    GET  /demo               a page to try it in a browser

Every model in this slot answers the same endpoint, so the voice pipeline needs
no per-model client -- which is the reason this folder does not simply ship the
checkpoint's own server.py. See engine.py for what that server does differently
and why each difference matters.

**`voice`, not `speaker`.** Their server names the field `speaker`, and pydantic
ignores fields it does not know, so an OpenAI client asking for `voice="Zoya"`
would be served Ira with nothing logged anywhere. `voice` is OpenAI's name and
the name the other TTS folders here use, so it is the name on the wire; the
speaker goes into the prompt in engine.py.

**`instructions` is the delivery description.** The model conditions on a
free-text `<description="...">` prefix -- emotion, accent, pace. That is exactly
what OpenAI's `instructions` field is for, and tts/indic-parler already maps it
the same way, so a caller can move between the two models without rewriting the
request.

Cancellation needs no polling here. When the caller hangs up, Starlette cancels
the body iterator, which throws into the async generator in engine.py, whose
`finally` aborts the vLLM request -- or, on the transformers engine, trips the
sampling tap so generation stops inside the model's own loop -- rather than
running to the end of a sentence nobody is listening to.
"""
from __future__ import annotations

import base64
import contextlib
import json
import logging
from pathlib import Path
from typing import Literal

import audio as audio_fmt
import uvicorn
from config import Config
from engine import PromptError, RumikTTSEngine, StreamStats, TTSGenerationError
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("rumik.server")

ResponseFormat = Literal["pcm", "wav", "mp3", "flac", "opus"]
StreamFormat = Literal["audio", "sse"]

#: Served at /demo, the slot's convention. Our own page, so there is no need for
#: the gateway's TTS_DEMO_PATH escape hatch -- that exists for folders vendored
#: whole, which serve their page wherever upstream put it.
DEMO_PAGE = Path(__file__).resolve().parent / "static" / "demo.html"


class SpeechRequest(BaseModel):
    """Body of POST /v1/audio/speech. OpenAI's schema, plus three extensions."""

    model_config = ConfigDict(protected_namespaces=())

    model: str | None = Field(
        None, description="Accepted for compatibility; this server serves one model."
    )
    input: str = Field(..., min_length=1,
                       description="Text to speak, in a native script or romanized.",
                       examples=["नमस्ते, आज आपका दिन कैसा रहा?"])
    voice: str | None = Field(
        None, description="Speaker from GET /v1/voices. Unlike Orpheus, the speaker does "
                          "NOT select the language -- every voice covers all 22.",
        examples=["Ira"],
    )
    instructions: str | None = Field(
        None,
        description="Delivery description: emotion, accent and pace, comma-separated, "
                    "e.g. 'happy, Hindi accent, steady pace'. Becomes the model's "
                    "<description=...> prefix.",
    )
    response_format: ResponseFormat = Field(
        "mp3", description="OpenAI's default is mp3. 'pcm' is raw 24 kHz mono s16le and is "
                           "what the voice pipeline asks for.",
    )
    stream_format: StreamFormat = Field(
        "audio",
        description="'audio' returns the audio body, chunked while generating; 'sse' "
                    "returns server-sent speech.audio.delta events carrying base64 audio.",
    )
    speed: float = Field(
        1.0, ge=0.25, le=4.0,
        description="Accepted for compatibility but IGNORED: this model has no rate "
                    "control, and resampling would shift pitch. Ask for pace in "
                    "`instructions` instead. A non-default value sets X-Speed-Ignored.",
    )
    # --- extensions beyond the OpenAI schema ---
    temperature: float | None = Field(
        None, ge=0.0, le=2.0, description="Extension: sampling temperature. Shipped default 0.8."
    )
    top_k: int | None = Field(
        None, ge=1, description="Extension: top-k sampling. Shipped default 30."
    )
    max_new_tokens: int | None = Field(
        None, ge=8,
        description="Extension: cap on generated audio tokens. Eight make one 80 ms "
                    "frame, so the default 3072 is about 30 s of speech -- the model "
                    "card's maximum. Hitting it cuts the audio off: X-Truncated on a "
                    "buffered response, `truncated` in the SSE done event.",
    )


def openai_error(status_code: int, message: str, param: str | None = None) -> JSONResponse:
    """Render an error in OpenAI's envelope.

    OpenAI clients read ``error.message``; FastAPI's default ``{"detail": ...}``
    reaches them as an opaque blob, so a wrong voice name surfaces in the SDK as
    an unhelpful string. Same status, same text, the shape clients parse.
    """
    kind = "invalid_request_error" if status_code < 500 else "server_error"
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": message, "type": kind, "param": param, "code": None}},
    )


def create_app(config: Config | None = None) -> FastAPI:
    """Build the server around one engine.

    A factory rather than a module-level app, so the engine's lifetime is tied
    to the application's and two configurations can exist in one process --
    which is what makes this testable without a GPU.
    """
    cfg = config or Config.from_env()
    logging.basicConfig(
        level=cfg.log_level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )

    @contextlib.asynccontextmanager
    async def lifespan(application: FastAPI):
        engine: RumikTTSEngine = application.state.engine
        # Awaited rather than threaded: vLLM's engine binds to the running loop.
        # The blocking parts inside start() go to a thread themselves, so
        # /health still answers "loading" throughout -- which is what lets the
        # gateway hold traffic back instead of sending it to a half-built model.
        await engine.start()
        application.state.ready = True
        log.info(
            "rumik-oss-1 on :%d (engine=%s voices=%s concurrency=%d chunk=%d frames)",
            cfg.port, cfg.engine, ", ".join(engine.speakers), cfg.max_concurrency,
            cfg.decode_chunk_frames,
        )
        try:
            yield
        finally:
            application.state.ready = False
            await engine.stop()

    app = FastAPI(title="rumik-oss-1 TTS", version="1.0.0", lifespan=lifespan)
    app.state.config = cfg
    app.state.engine = RumikTTSEngine(cfg)
    app.state.ready = False

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request: Request, exc: StarletteHTTPException):
        response = openai_error(exc.status_code, str(exc.detail))
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError):
        # OpenAI answers a malformed body with 400, not FastAPI's default 422.
        errors = exc.errors()
        first = errors[0] if errors else {}
        param = ".".join(str(p) for p in first.get("loc", ()) if p != "body") or None
        message = first.get("msg", "invalid request")
        return openai_error(400, f"{message} (at '{param}')" if param else message, param)

    if cfg.cors_origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=list(cfg.cors_origins),
            allow_methods=["*"], allow_headers=["*"],
        )

    # ------------------------------------------------------------------ meta
    @app.get("/health")
    async def health():
        """503 while loading.

        Not a defect: it makes "healthy" mean "will answer fast" rather than
        "the process is alive", which is what the gateway's probe and the
        container healthcheck both want.
        """
        engine: RumikTTSEngine = app.state.engine
        ready = app.state.ready
        return JSONResponse(
            {
                "status": "ok" if ready else "loading",
                "ready": ready,
                "model": cfg.model_name,
                "engine": cfg.engine,
                "voices": list(engine.speakers) if ready else [],
                "sample_rate": engine.sample_rate if ready else None,
                "frame_ms": round(engine.frame_ms, 2) if ready else None,
            },
            status_code=200 if ready else 503,
        )

    @app.get("/v1/models")
    async def list_models():
        return {
            "object": "list",
            "data": [{"id": cfg.model_name, "object": "model", "owned_by": "rumik-ai"}],
        }

    @app.get("/v1/voices")
    async def voices():
        """The roster, read from the checkpoint's own config rather than a file.

        Agent configuration needs these ids, and a hardcoded list is how a
        checkpoint change produces a voice name nothing answers to.
        """
        engine: RumikTTSEngine = app.state.engine
        return {
            "object": "list",
            "data": [{"id": name, "languages": "all"} for name in engine.speakers],
            "default": cfg.default_voice,
        }

    @app.get("/demo")
    async def demo():
        return FileResponse(DEMO_PAGE, media_type="text/html")

    # ------------------------------------------------------------- synthesis
    @app.post("/v1/audio/speech")
    async def speech(req: SpeechRequest):
        engine: RumikTTSEngine = app.state.engine
        if not app.state.ready:
            return openai_error(503, "the model is still loading")

        # Refused before any response object exists, so a bad request is a 400
        # rather than a 200 with an empty body. Once a StreamingResponse has
        # sent its status line, the only way left to signal failure is to stop
        # writing audio.
        try:
            prompt_ids, cap = engine.plan(
                text=req.input, voice=req.voice, instructions=req.instructions,
                max_new_tokens=req.max_new_tokens,
            )
        except PromptError as exc:
            return openai_error(400, str(exc))

        stats = StreamStats(frame_ms=engine.frame_ms)
        headers = {
            # What is in the body, so a client never has to know which model
            # answered. tests/test_tts_format_negotiation.py is why this is not
            # optional: two TTS models here disagree on sample width, and a
            # client that assumes hears noise rather than getting an error.
            "X-Audio-Format": req.response_format,
            "X-Sample-Rate": str(engine.sample_rate),
            "X-Channels": "1",
            "X-Voice": (req.voice or cfg.default_voice).strip(),
        }
        if req.speed != 1.0:
            headers["X-Speed-Ignored"] = str(req.speed)

        def pcm_stream():
            return engine.synthesize_stream(
                prompt_token_ids=prompt_ids, max_new_tokens=cap,
                temperature=req.temperature, top_k=req.top_k, stats=stats,
            )

        if req.stream_format == "sse":
            if not audio_fmt.encodes_incrementally(req.response_format):
                # flac and opus buffer everything until close, so every delta
                # would be empty and the whole clip would arrive as one enormous
                # final event.
                return openai_error(
                    400,
                    f"response_format {req.response_format!r} cannot be delivered over SSE: "
                    f"its encoder only produces bytes when the file is closed. Use 'pcm', "
                    f"'mp3' or 'wav' with stream_format='sse', or request "
                    f"{req.response_format!r} with stream_format='audio' to get it as one "
                    f"complete file.",
                    "response_format",
                )
            return StreamingResponse(
                _sse_events(pcm_stream, req.response_format, stats),
                media_type="text/event-stream",
                headers={**headers, "Cache-Control": "no-store", "X-Accel-Buffering": "no"},
            )

        # stream_format="audio". pcm and mp3 are chunked as they are produced,
        # so a client that reads incrementally hears audio in ~160 ms while one
        # that calls create() just buffers the body. wav, flac and opus are
        # encoded in one pass instead: their headers are only correct once the
        # length is known, and a client cannot be sent a correction for bytes it
        # already has.
        if not audio_fmt.streams_incrementally(req.response_format):
            encoder = audio_fmt.make_encoder(req.response_format, streaming=False)
            body = bytearray()
            try:
                async for pcm in pcm_stream():
                    body += encoder.feed(pcm)
                body += encoder.close()
            except PromptError as exc:
                return openai_error(400, str(exc))
            except TTSGenerationError as exc:
                log.exception("synthesis failed")
                return openai_error(500, f"synthesis failed: {exc}")
            if stats.frames == 0:
                return openai_error(500, "no audio produced")
            return Response(
                content=bytes(body), media_type=encoder.media_type,
                headers={**headers, **_timing_headers(stats)},
            )

        return StreamingResponse(
            _audio_chunks(pcm_stream, req.response_format),
            media_type=audio_fmt.media_type(req.response_format),
            headers={**headers, "X-Accel-Buffering": "no"},
        )

    return app


def _timing_headers(stats: StreamStats) -> dict[str, str]:
    """This request's own measurements -- never another concurrent stream's.

    Only on the buffered path. A streamed response sends its headers before the
    first token exists, so there is nothing true to put in them; the SSE `done`
    event carries the same numbers for that case.
    """
    out = {
        "X-Audio-Duration-Sec": f"{stats.audio_ms / 1000.0:.2f}",
        "X-Generation-Ms": f"{stats.gen_ms:.1f}",
        # Tokens, because RTF alone cannot tell a slow GPU from a model emitting
        # tokens the de-interleaver discards: both show as more time for the same
        # audio. Diagnosing that once needed a hand-written script against the
        # raw model, which is a thing a response should never require.
        "X-Tokens": str(stats.tokens),
    }
    if stats.truncated:
        # The body is complete as a file but the utterance is not: generation
        # hit the token cap mid-sentence. Said out loud rather than left for a
        # listener to notice.
        out["X-Truncated"] = "true"
    if stats.tokens_per_s is not None:
        out["X-Tokens-Per-Sec"] = f"{stats.tokens_per_s:.1f}"
    if stats.ttfa_ms is not None:
        out["X-TTFA-Ms"] = f"{stats.ttfa_ms:.1f}"
    if stats.rtf is not None:
        out["X-RTF"] = f"{stats.rtf:.3f}"
    return out


async def _audio_chunks(pcm_stream, fmt: str):
    """Chunked audio body. Errors mid-stream can only truncate: headers are gone."""
    encoder = audio_fmt.make_encoder(fmt, streaming=True)
    try:
        async for pcm in pcm_stream():
            chunk = encoder.feed(pcm)
            if chunk:
                yield chunk
        tail = encoder.close()
        if tail:
            yield tail
    except (PromptError, TTSGenerationError):
        # The status line went out long ago, so the only honest signal left is
        # to stop writing. Logged loudly; the client sees a short stream, which
        # its own error handling treats as a failure.
        log.exception("streaming synthesis failed")


async def _sse_events(pcm_stream, fmt: str, stats: StreamStats):
    """OpenAI's SSE speech stream: audio deltas, then a terminal done event."""
    encoder = audio_fmt.make_encoder(fmt, streaming=True)

    def event(payload: dict) -> bytes:
        return f"data: {json.dumps(payload)}\n\n".encode()

    def delta(chunk: bytes) -> bytes:
        return event({
            "type": "speech.audio.delta",
            "audio": base64.b64encode(chunk).decode("ascii"),
        })

    try:
        async for pcm in pcm_stream():
            chunk = encoder.feed(pcm)
            if chunk:
                yield delta(chunk)
        tail = encoder.close()
        if tail:
            yield delta(tail)
        yield event({
            "type": "speech.audio.done",
            "usage": {"output_tokens": stats.tokens, "total_tokens": stats.tokens},
            "truncated": stats.truncated,
            "audio": {
                "duration_ms": round(stats.audio_ms, 1),
                "format": fmt,
                "sample_rate": audio_fmt.SAMPLE_RATE,
            },
            "timings": stats.summary(),
        })
    except (PromptError, TTSGenerationError) as exc:
        log.exception("sse synthesis failed")
        yield event({"type": "error",
                     "error": {"message": str(exc), "type": "synthesis_error"}})


app = create_app()


def main() -> None:
    cfg = Config.from_env()
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, log_level=cfg.log_level.lower())


if __name__ == "__main__":
    main()
