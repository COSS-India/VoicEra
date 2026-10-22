"""Higgs TTS 3 on the slot's OpenAI speech endpoint.

    POST /v1/audio/speech    OpenAI-compatible; streams while generating
    GET  /health             503 until the sidecar is up and a voice is usable
    GET  /v1/voices          the speaker roster and the instructions vocabulary
    GET  /v1/models          OpenAI-compatible single-model list

This is an adapter, not an engine. Generation runs in the SGLang-Omni sidecar
this folder brings in compose.extra.yml; that sidecar already speaks an
OpenAI-shaped `/v1/audio/speech`, so most of this file is the translation the
slot needs and the sidecar does not do:

* **`voice`** is a roster name (voices/manifest.json), turned into a reference
  clip plus its transcript. Higgs has no built-in speakers -- a voice IS a clip.
* **`instructions`** takes the fixed Higgs delivery tags only (tags.py), and
  becomes the tag prefix the model wants at the very start of the text.
* **`speed`** is honoured, unlike rumik and indic-mio: it is rounded to one of
  Higgs's four speed tags rather than resampled, so pitch is untouched.
* **Every response says what it is**: X-Audio-Format and X-Sample-Rate, which
  is the slot contract (tests/test_tts_format_negotiation.py).
* **Errors are OpenAI's envelope** `{"error": {message, type, param, code}}`.

The sidecar is always asked for raw PCM; every other response_format is encoded
here (audio.py), so pcm -- what the voice pipeline asks for -- is a byte-for-byte
pass-through with no decode or re-encode in the path.
"""
from __future__ import annotations

import base64
import contextlib
import json
import logging
from typing import Literal

import audio as audio_fmt
import uvicorn
from config import Config
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException as StarletteHTTPException
from tags import (
    NONE,
    TagError,
    apply_speed,
    check_inline_tags,
    compose_input,
    instruction_options,
    parse_instructions,
)
from upstream import PcmStream, SidecarClient, SidecarError, StreamStats
from voices import Roster, VoiceError

log = logging.getLogger("higgs.server")

ResponseFormat = Literal["pcm", "wav", "mp3", "flac", "opus"]
StreamFormat = Literal["audio", "sse"]

#: The voice name that means "no reference clip": Higgs picks a speaker itself,
#: a different one on every request. Only accepted with HIGGS_ALLOW_ZERO_SHOT,
#: which exists for bringing the slot up before any clip has been fetched.
ZERO_SHOT_VOICE = "default"


class SpeechRequest(BaseModel):
    """Body of POST /v1/audio/speech. OpenAI's schema, plus four extensions."""

    model_config = ConfigDict(protected_namespaces=())

    model: str | None = Field(
        None, description="Accepted for compatibility; this server serves one model."
    )
    input: str = Field(..., min_length=1,
                       description="Text to speak. Inline Higgs tags (pauses, sound effects) "
                                   "may be written where they should happen.",
                       examples=["नमस्ते, आज आपका दिन कैसा रहा?"])
    voice: str | None = Field(
        None, description="Speaker from GET /v1/voices. Does not select the language; "
                          "it sets the timbre and accent of the reference clip.",
        examples=["Aditi"],
    )
    instructions: str | None = Field(
        None,
        description="Delivery tags from the fixed Higgs list, e.g. "
                    "'emotion:contentment, prosody:pitch_low'. Free text is refused.",
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
        description="Rounded to Higgs's nearest speed step (0.65, 0.85, 1.0, 1.2, 1.4). "
                    "X-Speed-Applied reports the step used.",
    )
    # --- extensions beyond the OpenAI schema ---
    temperature: float | None = Field(None, ge=0.0, le=2.0,
                                      description="Extension: sampling temperature. Default 0.8.")
    top_k: int | None = Field(None, ge=1, description="Extension: top-k sampling. Default 50.")
    top_p: float | None = Field(None, gt=0.0, le=1.0,
                                description="Extension: nucleus sampling. Default 0.8.")
    max_new_tokens: int | None = Field(
        None, ge=1,
        description="Extension: cap on generated audio frames (25 per second of speech). "
                    "Hitting it cuts the audio off: X-Truncated / SSE `truncated`.",
    )


def openai_error(status_code: int, message: str, param: str | None = None) -> JSONResponse:
    """An error in OpenAI's envelope, which is what OpenAI clients parse."""
    kind = "invalid_request_error" if status_code < 500 else "server_error"
    return JSONResponse(
        status_code=status_code,
        content={"error": {"message": message, "type": kind, "param": param, "code": None}},
    )


def create_app(config: Config | None = None, sidecar: SidecarClient | None = None) -> FastAPI:
    """Build the server. A factory, so tests can hand in a stub sidecar."""
    cfg = config or Config.from_env()
    logging.basicConfig(
        level=cfg.log_level, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )
    client = sidecar or SidecarClient(cfg.sidecar_url, cfg.sidecar_timeout_s)
    roster = Roster.load(cfg.voices_dir)

    @contextlib.asynccontextmanager
    async def lifespan(_application: FastAPI):
        log.info(
            "higgs-tts-3 adapter on :%d -> %s (voices with clips: %s; zero-shot %s)",
            cfg.port, cfg.sidecar_url,
            ", ".join(v.name for v in roster.available) or "none",
            "allowed" if cfg.allow_zero_shot else "off",
        )
        try:
            yield
        finally:
            await client.aclose()

    app = FastAPI(title="higgs-tts-3 TTS", version="1.0.0", lifespan=lifespan)
    app.state.config = cfg
    app.state.roster = roster
    app.state.sidecar = client

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
        """200 only when a request would be served: sidecar up AND a voice usable.

        A sidecar that is healthy while every voice lacks its clip would make
        "healthy" mean "every request fails with 503", so that is reported as
        not ready, naming the reason.
        """
        sidecar_ok, sidecar_status = await client.health()
        voices_ok = bool(roster.available) or cfg.allow_zero_shot
        ready = sidecar_ok and voices_ok
        if not sidecar_ok:
            status = "loading"
        elif not voices_ok:
            status = "no_voices"
        else:
            status = "ok"
        return JSONResponse(
            {
                "status": status,
                "ready": ready,
                "model": cfg.model_name,
                "sidecar": sidecar_status,
                "voices": [v.name for v in roster.available],
                "zero_shot": cfg.allow_zero_shot,
                "sample_rate": audio_fmt.SAMPLE_RATE,
            },
            status_code=200 if ready else 503,
        )

    @app.get("/v1/models")
    async def list_models():
        return {
            "object": "list",
            "data": [{"id": cfg.model_name, "object": "model", "owned_by": "bosonai"}],
        }

    @app.get("/v1/voices")
    async def voices():
        """The roster, and what `instructions` accepts -- what agent config is built from."""
        data = [
            {"id": v.name, "gender": v.gender, "language": v.language,
             "languages": "all", "available": v.available}
            for v in roster.voices
        ]
        return {
            "object": "list",
            "data": data,
            "default": cfg.default_voice,
            "instructions": [NONE, *instruction_options()],
        }

    # ------------------------------------------------------------- synthesis
    @app.post("/v1/audio/speech")
    async def speech(req: SpeechRequest):
        # Everything is checked before the sidecar is called, so a bad request
        # is a 400 with a reason rather than GPU time followed by an error.
        try:
            payload, headers = _plan(req, cfg, roster)
        except TagError as exc:
            return openai_error(400, str(exc), exc.param)
        except VoiceError as exc:
            return openai_error(exc.status, str(exc), "voice")
        except ValueError as exc:
            return openai_error(400, str(exc), "input")

        if req.stream_format == "sse" and not audio_fmt.encodes_incrementally(req.response_format):
            # flac and opus buffer everything until close: over SSE that is no
            # deltas and then one enormous one.
            return openai_error(
                400,
                f"response_format {req.response_format!r} cannot be delivered over SSE: its "
                f"encoder only produces bytes when the file is closed. Use 'pcm', 'mp3' or "
                f"'wav' with stream_format='sse', or stream_format='audio' for one file.",
                "response_format",
            )

        try:
            stream = await client.open_stream(payload)
        except SidecarError as exc:
            return openai_error(exc.status, str(exc), exc.param)
        if stream.sample_rate != audio_fmt.SAMPLE_RATE:
            await stream.aclose()
            return openai_error(
                502,
                f"the sidecar streams {stream.sample_rate} Hz but this server encodes "
                f"{audio_fmt.SAMPLE_RATE} Hz; refusing rather than playing at the wrong speed",
            )

        headers = {
            **headers,
            # What is in the body, so a client never has to know which model
            # answered -- the slot contract.
            "X-Audio-Format": req.response_format,
            "X-Sample-Rate": str(stream.sample_rate),
            "X-Channels": "1",
        }

        if req.stream_format == "sse":
            return StreamingResponse(
                _sse_events(stream, req.response_format),
                media_type="text/event-stream",
                headers={**headers, "Cache-Control": "no-store", "X-Accel-Buffering": "no"},
                background=BackgroundTask(stream.aclose),
            )

        if audio_fmt.streams_incrementally(req.response_format):
            return StreamingResponse(
                _audio_chunks(stream, req.response_format),
                media_type=audio_fmt.media_type(req.response_format),
                headers={**headers, "X-Accel-Buffering": "no"},
                # Belt and braces: if the caller is gone before the body starts,
                # the generator's own `finally` never runs, so this closes the
                # sidecar connection (and so aborts generation) instead.
                background=BackgroundTask(stream.aclose),
            )

        # wav, flac, opus: one pass, so the container's length fields are true.
        encoder = audio_fmt.make_encoder(req.response_format, streaming=False)
        body = bytearray()
        try:
            async for pcm in stream.chunks():
                body += encoder.feed(pcm)
            body += encoder.close()
        except SidecarError as exc:
            return openai_error(exc.status, str(exc))
        if stream.stats.pcm_bytes == 0:
            return openai_error(502, "the model produced no audio")
        return Response(content=bytes(body), media_type=encoder.media_type,
                        headers={**headers, **_timing_headers(stream.stats)})

    return app


def _plan(req: SpeechRequest, cfg: Config, roster: Roster) -> tuple[dict, dict[str, str]]:
    """The sidecar request, and the headers that describe it. Raises on a bad request."""
    text = req.input.strip()
    if not text:
        raise ValueError("`input` is empty")
    if len(text) > cfg.max_input_chars:
        raise ValueError(
            f"`input` is {len(text)} characters; this server takes at most "
            f"{cfg.max_input_chars} per request (HIGGS_MAX_INPUT_CHARS). Split it into sentences."
        )
    check_inline_tags(text)

    instructions = req.instructions if req.instructions is not None else cfg.default_instructions
    delivery = apply_speed(parse_instructions(instructions), req.speed)

    cap = req.max_new_tokens or cfg.max_new_tokens_default
    if cap > cfg.max_new_tokens_limit:
        raise TagError(
            f"max_new_tokens {cap} exceeds this server's limit of {cfg.max_new_tokens_limit}",
            "max_new_tokens",
        )

    payload: dict = {
        "model": cfg.model_name,
        "input": compose_input(text, delivery),
        "voice": ZERO_SHOT_VOICE,
        "response_format": "pcm",
        "stream": True,
        # Speed is a tag in the text; the sidecar's own `speed` would resample.
        "speed": 1.0,
        "temperature": req.temperature if req.temperature is not None else cfg.temperature,
        "top_k": req.top_k if req.top_k is not None else cfg.top_k,
        "top_p": req.top_p if req.top_p is not None else cfg.top_p,
        "max_new_tokens": cap,
    }
    if cfg.initial_chunk_frames is not None:
        payload["initial_codec_chunk_frames"] = cfg.initial_chunk_frames

    name = (req.voice or "").strip() or cfg.default_voice
    if name.casefold() == ZERO_SHOT_VOICE:
        if not cfg.allow_zero_shot:
            raise VoiceError(
                "voice 'default' (no reference clip, a random speaker per request) is "
                "disabled; name a voice from GET /v1/voices, or set HIGGS_ALLOW_ZERO_SHOT=true",
                400,
            )
        voice_name = ZERO_SHOT_VOICE
    else:
        voice = roster.resolve(name)
        reference = {"audio_path": f"{cfg.sidecar_voices_dir}/refs/{voice.ref}"}
        if voice.text:
            reference["text"] = voice.text
        payload["references"] = [reference]
        voice_name = voice.name

    headers = {
        "X-Voice": voice_name,
        "X-Speed-Applied": str(delivery.slots.get("speed", "normal")),
    }
    if delivery.slots:
        headers["X-Delivery-Tags"] = delivery.prefix()
    return payload, headers


def _timing_headers(stats: StreamStats) -> dict[str, str]:
    """Only on the buffered path: a streamed response's headers predate the audio."""
    out = {
        "X-Audio-Duration-Sec": f"{stats.audio_ms / 1000.0:.2f}",
        "X-Generation-Ms": f"{stats.gen_ms:.1f}",
    }
    if stats.ttfa_ms is not None:
        out["X-TTFA-Ms"] = f"{stats.ttfa_ms:.1f}"
    if stats.rtf is not None:
        out["X-RTF"] = f"{stats.rtf:.3f}"
    if stats.truncated:
        out["X-Truncated"] = "true"
    return out


async def _audio_chunks(stream: PcmStream, fmt: str):
    """Chunked audio body. Errors mid-stream can only truncate: the headers are gone."""
    encoder = audio_fmt.make_encoder(fmt, streaming=True)
    chunks = stream.chunks()
    try:
        async for pcm in chunks:
            out = encoder.feed(pcm)
            if out:
                yield out
        tail = encoder.close()
        if tail:
            yield tail
    except SidecarError:
        log.exception("streaming synthesis failed")
    finally:
        # Reached on a client hang-up too (GeneratorExit): closing the inner
        # generator closes the sidecar connection, which aborts generation.
        await chunks.aclose()
    if stream.stats.truncated:
        log.warning("utterance cut off at max_new_tokens (%s)", stream.stats.summary())


async def _sse_events(stream: PcmStream, fmt: str):
    """OpenAI's SSE speech stream: audio deltas, then a terminal done event."""
    encoder = audio_fmt.make_encoder(fmt, streaming=True)
    chunks = stream.chunks()

    def event(payload: dict) -> bytes:
        return f"data: {json.dumps(payload)}\n\n".encode()

    def delta(chunk: bytes) -> bytes:
        return event({"type": "speech.audio.delta",
                      "audio": base64.b64encode(chunk).decode("ascii")})

    try:
        async for pcm in chunks:
            out = encoder.feed(pcm)
            if out:
                yield delta(out)
        tail = encoder.close()
        if tail:
            yield delta(tail)
        stats = stream.stats
        yield event({
            "type": "speech.audio.done",
            "truncated": stats.truncated,
            "audio": {"duration_ms": round(stats.audio_ms, 1), "format": fmt,
                      "sample_rate": stream.sample_rate},
            "timings": stats.summary(),
        })
    except SidecarError as exc:
        log.exception("sse synthesis failed")
        yield event({"type": "error", "error": {"message": str(exc), "type": "synthesis_error"}})
    finally:
        await chunks.aclose()


app = create_app()


def main() -> None:
    cfg = Config.from_env()
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, log_level=cfg.log_level.lower())


if __name__ == "__main__":
    main()
