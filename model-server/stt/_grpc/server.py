"""gRPC front door for the STT slot, proxying to the model's own WebSocket.

Why a facade and not a second server: `stt/indic-nemotron/` is vendored from
upstream byte for byte, and a test enforces that. Reimplementing the session
here would fork it. Proxying `/v1/asr/ws` instead means one gRPC stream is one
model session, so batching, VAD and vocabulary slicing behave identically
whichever door a caller arrived through -- and a re-push from upstream stays a
clean replace.

This exists because NVIDIA Cloud Functions has no WebSocket invocation path,
and a telephony leg needs audio flowing in while transcripts flow back. It is
opt-in: nothing attaches it unless USE_STT_GRPC is set, so a deployment that
does not need it is byte-identical to one from before this folder existed.

Deliberately NOT done here:

  * No language table. The model owns LANGUAGE_PROMPT_MAP; duplicating those 27
    codes is a copy that would drift. An unknown language is rejected upstream
    and its error -- which lists what is valid -- is returned as the RPC status.
  * No resampling. 16 kHz LINEAR16 or INVALID_ARGUMENT. A resampler here would
    be a transcription-quality decision buried in a transport component.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import signal
import urllib.error
import urllib.request

# asr_pb2* are generated from asr.proto at image build time and by the test
# fixture, so they do not exist in a fresh checkout. Flat imports, not
# `from . import`, because the folder is a container root rather than a package.
import asr_pb2
import asr_pb2_grpc
import grpc
import websockets
from grpc_health.v1 import health, health_pb2, health_pb2_grpc

log = logging.getLogger("asr-grpc")

STT_WS_URL = os.environ.get("STT_GRPC_UPSTREAM_WS", "ws://stt:8000/v1/asr/ws")
#: Read-only readiness probe. A WebSocket probe would open a real ASR session
#: every few seconds, inflating active_streams and taking a batch slot.
STT_HEALTH_URL = os.environ.get("STT_GRPC_UPSTREAM_HEALTH", "http://stt:8000/health")
REQUIRED_SAMPLE_RATE = int(os.environ.get("STT_GRPC_SAMPLE_RATE", "16000"))
LISTEN = os.environ.get("STT_GRPC_LISTEN", "0.0.0.0:8004")
MAX_MESSAGE_BYTES = int(os.environ.get("STT_GRPC_MAX_MESSAGE_BYTES", str(4 * 1024 * 1024)))
OPEN_TIMEOUT_S = float(os.environ.get("STT_GRPC_OPEN_TIMEOUT_S", "30"))
PROBE_INTERVAL_S = float(os.environ.get("STT_GRPC_PROBE_INTERVAL_S", "5"))
#: Frame size the model's wire contract expects (WIRE_CHUNK_SAMPLES * 2).
WIRE_CHUNK_BYTES = 5120

#: "hi-IN" -> "hi". Riva-shaped clients send BCP-47; the model wants the bare
#: code. Bhili has no region anyone agrees on, so bhb and bhb-IN both work.
_REGION = re.compile(r"^([A-Za-z]{2,3})(?:[-_][A-Za-z0-9]+)*$")


def bare_language(code: str) -> str:
    m = _REGION.match((code or "").strip())
    return m.group(1).lower() if m else (code or "").strip().lower()


def validate(config) -> str:
    """The language to send upstream, or ValueError naming what is wrong."""
    if not config.language.strip():
        raise ValueError(
            "config.language is required: this checkpoint has no auto-detection, "
            "because its output layer is sliced per language and an unsliced "
            "decode emits cross-script nonsense. Name a language."
        )
    rate = config.sample_rate_hz or REQUIRED_SAMPLE_RATE
    if rate != REQUIRED_SAMPLE_RATE:
        raise ValueError(
            f"sample_rate_hz must be {REQUIRED_SAMPLE_RATE}, got {rate}. Audio is "
            f"not resampled here; convert before sending."
        )
    if config.encoding not in (asr_pb2.ENCODING_UNSPECIFIED, asr_pb2.LINEAR16):
        raise ValueError("encoding must be LINEAR16 (16-bit signed, little endian)")
    return bare_language(config.language)


def error_frame(raw) -> str | None:
    """The model's message if this frame reports a fatal error, else None.

    The model answers a bad request by sending {"error": ...} and closing 1011.
    That message is the useful one -- it lists every language it accepts -- so it
    becomes the RPC status. It used to be yielded as a Warning, and then the 1011
    close raised ConnectionClosedError out of the servicer, so the caller got
    `UNKNOWN: Unexpected <class 'websockets.exceptions.ConnectionClosedError'>`
    with the real explanation buried in an event it had no reason to read.
    """
    if isinstance(raw, (bytes, bytearray)):
        return None
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return str(msg["error"]) if "error" in msg else None


def translate(raw, want_interim: bool):
    """One WebSocket frame -> one StreamingResponse, or None to swallow it."""
    if isinstance(raw, (bytes, bytearray)):
        return None
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return None

    if msg.get("status") == "ready":
        return asr_pb2.StreamingResponse(started=asr_pb2.SessionStarted(
            session_id=msg.get("session_id", ""),
            model_chunk_ms=int(msg.get("model_chunk_ms") or 0),
            expected_sample_rate_hz=int(msg.get("expected_sample_rate") or 0),
            build_id=msg.get("build_id", ""),
            language=msg.get("language", ""),
        ))
    if "text" in msg:
        is_final = bool(msg.get("is_final"))
        if not is_final and not want_interim:
            return None
        return asr_pb2.StreamingResponse(transcript=asr_pb2.Transcript(
            text=msg.get("text", ""),
            is_final=is_final,
            latency_ms=float(msg.get("latency_ms") or 0.0),
            language=msg.get("language", ""),
        ))
    if msg.get("samples_dropped"):
        return asr_pb2.StreamingResponse(warning=asr_pb2.Warning(
            code="samples_dropped",
            message="the model dropped buffered audio to keep up with real time",
            samples_dropped=int(msg["samples_dropped"]),
        ))
    return None


#: Messages to swallow when rejecting a stream. A caller that keeps writing
#: past this gets the status anyway; the point is to outlast a normal client's
#: in-flight buffer, not to read a whole call it has already been refused.
DRAIN_LIMIT = int(os.environ.get("STT_GRPC_DRAIN_LIMIT", "256"))


async def _reject(context, request_iterator, code, details) -> None:
    """End a response-streaming call with a status the caller can act on.

    Two things had to change from the obvious version, both found by running
    the tests twenty times instead of once:

    `context.abort()` raises inside the generator. With a client still writing
    audio behind its config, that races its in-flight sends and the CLIENT
    reports `INTERNAL "Internal error from Core"` rather than the status we
    set -- about 1 run in 10.

    Setting the code and returning immediately is no better (8 in 20): a server
    that stops reading mid-stream makes the client's pending writes fail, and a
    failed write surfaces as INTERNAL on the client whatever the server said.

    So: set the status, then drain what the caller is still sending, and let the
    call end on its own. UNAVAILABLE then reliably means "retry, the model is
    still loading", INVALID_ARGUMENT means "fix the request", and INTERNAL means
    neither -- which is the whole point of returning a status at all.
    """
    context.set_code(code)
    context.set_details(details)
    with contextlib.suppress(Exception):
        for _ in range(DRAIN_LIMIT):
            await request_iterator.__anext__()


class _Turns:
    """Flushes asked for, finals seen. Shared between the reader and the pump."""

    __slots__ = ("flushes", "finals")

    def __init__(self) -> None:
        self.flushes = 0
        self.finals = 0


class AsrServicer(asr_pb2_grpc.AsrServicer):
    async def StreamingRecognize(self, request_iterator, context):
        try:
            first = await request_iterator.__anext__()
        except StopAsyncIteration:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("stream closed before a config message")
            return
        if first.WhichOneof("payload") != "config":
            await _reject(context, request_iterator, grpc.StatusCode.INVALID_ARGUMENT,
                          "the first message must be a StreamingConfig")
            return
        try:
            language = validate(first.config)
        except ValueError as exc:
            await _reject(context, request_iterator,
                          grpc.StatusCode.INVALID_ARGUMENT, str(exc))
            return

        want_interim = not first.config.disable_interim_results
        try:
            ws = await websockets.connect(f"{STT_WS_URL}?language={language}",
                                          max_size=None, open_timeout=OPEN_TIMEOUT_S)
        except Exception as exc:                                    # noqa: BLE001
            # UNAVAILABLE, not INTERNAL: the model may simply still be loading,
            # which is the normal state for minutes after a start.
            await _reject(context, request_iterator, grpc.StatusCode.UNAVAILABLE,
                          f"speech model is not reachable: {exc}")
            return

        # A telephony leg has many finals: one per VAD segment, or one per
        # explicit CommitTurn when the VAD is off. So "is_final" alone does not
        # end the RPC -- the LAST final does, the one answering the flush we
        # sent on half-close.
        #
        # Counting, not a flag. A flag set when the caller half-closes is racy:
        # the request iterator can drain before the reader has caught up, and
        # then an earlier turn's final looks like the last one and the call ends
        # a turn early. `turns` counts flushes sent; the reader waits for that
        # many finals.
        eos_sent = asyncio.Event()
        turns = _Turns()
        # A config error raised by the pump cannot abort from its own task
        # without the same race, so it is carried back here instead.
        pump_error: list[str] = []

        # The model named a problem with the request (bad language, say).
        rejected: list[str] = []
        # The model went away without explaining. Different status, different fix.
        vanished: list[str] = []

        async with ws:
            pump = asyncio.create_task(
                self._pump_audio(request_iterator, ws, eos_sent, pump_error, turns))
            try:
                async for message in ws:
                    problem = error_frame(message)
                    if problem is not None:
                        rejected.append(problem)
                        break
                    event = translate(message, want_interim)
                    if event is None:
                        continue
                    yield event
                    if event.WhichOneof("event") == "transcript" and event.transcript.is_final:
                        turns.finals += 1
                        if eos_sent.is_set() and turns.finals >= turns.flushes:
                            return
            except websockets.ConnectionClosed as exc:
                # Only a surprise if the model did not already say why. Without
                # this the exception escaped the servicer and the caller saw
                # UNKNOWN with a websockets class name in the details.
                if not rejected:
                    vanished.append(str(exc))
            finally:
                pump.cancel()
                await asyncio.gather(pump, return_exceptions=True)

        if pump_error:
            await _reject(context, request_iterator,
                          grpc.StatusCode.INVALID_ARGUMENT, pump_error[0])
        elif rejected:
            # The model's own text, which lists what it does accept.
            await _reject(context, request_iterator,
                          grpc.StatusCode.INVALID_ARGUMENT, rejected[0])
        elif vanished:
            await _reject(context, request_iterator, grpc.StatusCode.UNAVAILABLE,
                          f"the model closed the stream: {vanished[0]}")

    async def _pump_audio(self, request_iterator, ws, eos_sent, errors, turns) -> None:
        """Audio in. On half-close, ask the model to finalise the turn."""
        async for req in request_iterator:
            kind = req.WhichOneof("payload")
            if kind == "audio":
                if req.audio:
                    await ws.send(req.audio)
            elif kind == "commit":
                # End the turn without ending the call. With ASR_VAD=0 this is
                # the ONLY thing that finalises a transcript, so a caller doing
                # its own endpointing depends on it; with VAD on it finalises
                # early instead of waiting out the silence window.
                turns.flushes += 1
                await ws.send(json.dumps({"action": "flush_eos"}))
            elif kind == "config":
                # A second config switches language mid-stream, which the model
                # supports and resets its segment for.
                try:
                    lang = validate(req.config)
                except ValueError as exc:
                    errors.append(str(exc))
                    await ws.close()
                    return
                await ws.send(json.dumps({"action": "set_language", "language": lang}))
        turns.flushes += 1
        await ws.send(json.dumps({"action": "flush_eos"}))
        eos_sent.set()

    async def Recognize(self, request, context):
        """Whole utterance in one call, for parity with the HTTP route."""
        try:
            language = validate(request.config)
        except ValueError as exc:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
        try:
            ws = await websockets.connect(f"{STT_WS_URL}?language={language}",
                                          max_size=None, open_timeout=OPEN_TIMEOUT_S)
        except Exception as exc:                                    # noqa: BLE001
            await context.abort(grpc.StatusCode.UNAVAILABLE,
                                f"speech model is not reachable: {exc}")
        final, lang = "", language
        async with ws:
            audio = request.audio
            for i in range(0, len(audio), WIRE_CHUNK_BYTES):
                await ws.send(audio[i:i + WIRE_CHUNK_BYTES])
            await ws.send(json.dumps({"action": "flush_eos"}))
            async for message in ws:
                if isinstance(message, (bytes, bytearray)):
                    continue
                msg = json.loads(message)
                if "text" in msg and msg.get("is_final"):
                    final, lang = msg.get("text", ""), msg.get("language", language)
                    break
        return asr_pb2.RecognizeResponse(text=final, language=lang)


def _upstream_ready() -> bool:
    """True when the model reports it can serve. Blocking; called in a thread."""
    try:
        with urllib.request.urlopen(STT_HEALTH_URL, timeout=3) as resp:
            if resp.status != 200:
                return False
            body = json.loads(resp.read() or b"{}")
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return False
    loaded = body.get("models_loaded")
    # /health answers 503 until the checkpoints are in, so 200 is already the
    # signal. models_loaded is checked too when present: a Bhili checkpoint
    # that failed to load still serves 26 languages, and refusing traffic for
    # that would be worse than serving it.
    return bool(loaded.get("multilingual", True)) if isinstance(loaded, dict) else True


async def track_upstream(checker) -> None:
    serving = None
    while True:
        ok = await asyncio.to_thread(_upstream_ready)
        if ok != serving:
            serving = ok
            await checker.set("", health_pb2.HealthCheckResponse.SERVING if ok
                              else health_pb2.HealthCheckResponse.NOT_SERVING)
            log.info("upstream %s", "ready" if ok else "not ready")
        await asyncio.sleep(PROBE_INTERVAL_S)


async def serve() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    server = grpc.aio.server(options=[
        ("grpc.max_receive_message_length", MAX_MESSAGE_BYTES),
        ("grpc.max_send_message_length", MAX_MESSAGE_BYTES),
    ])
    asr_pb2_grpc.add_AsrServicer_to_server(AsrServicer(), server)

    # NVCF gates traffic on health, and the checkpoints take minutes to restore.
    # Reporting SERVING before the model answers would send it live calls it
    # cannot yet serve.
    checker = health.aio.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(checker, server)
    await checker.set("", health_pb2.HealthCheckResponse.NOT_SERVING)
    probe = asyncio.create_task(track_upstream(checker))

    server.add_insecure_port(LISTEN)
    await server.start()
    log.info("asr-grpc on %s -> %s", LISTEN, STT_WS_URL)

    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, lambda: stop.done() or stop.set_result(None))
    await stop
    probe.cancel()
    await server.stop(grace=5)


if __name__ == "__main__":
    asyncio.run(serve())
