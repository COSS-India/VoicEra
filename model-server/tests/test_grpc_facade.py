"""The gRPC front door, and the promise that it changes nothing for anyone else.

Two jobs, and the second is the more important one.

1. The facade translates: gRPC bidirectional streaming in, the model's own
   /v1/asr/ws out, one gRPC call to one model session. Exercised against a stub
   WebSocket that speaks the model's protocol, so no GPU is involved.

2. IT IS INERT UNLESS ASKED FOR. An adopter who does not set USE_STT_GRPC must
   get a deployment identical to one from before stt/_grpc/ existed -- same file
   list, same resolved services, same ports, same image for the model. That is
   asserted by diffing `docker compose config`, not by reading the overlay and
   believing it.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
FACADE = ROOT / "stt" / "_grpc"

pytestmark = pytest.mark.skipif(not FACADE.is_dir(), reason="gRPC facade not in this checkout")


# ----------------------------------------------------------- isolation (no grpc needed)

needs_docker = pytest.mark.skipif(
    subprocess.run(["docker", "compose", "version"], capture_output=True).returncode != 0,
    reason="docker compose not available",
)


def compose_files(**env) -> str:
    out = subprocess.run(
        ["sh", str(ROOT / "compose-files.sh")],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", **env},
    )
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_the_overlay_is_not_attached_unless_asked_for():
    """The whole isolation promise starts here: unset means unnamed."""
    assert "compose.grpc.yml" not in compose_files(), (
        "compose.grpc.yml is in the file list with USE_STT_GRPC unset; every "
        "adopter would get the gRPC service whether they wanted it or not"
    )
    assert "compose.grpc.yml" in compose_files(USE_STT_GRPC="1"), \
        "USE_STT_GRPC=1 did not attach the overlay"


def test_an_empty_value_is_still_off():
    """`USE_STT_GRPC=` in a .env is a line someone left behind, not a request."""
    assert "compose.grpc.yml" not in compose_files(USE_STT_GRPC="")


@needs_docker
def test_the_model_and_gateway_services_are_untouched_by_the_overlay():
    """The overlay may ADD a service. It may not change an existing one.

    This is the test that makes "it does not affect other adopters" checkable
    rather than a claim in a comment: resolve the stack with and without the
    overlay and require every pre-existing service to be byte-identical.
    """
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "COMPOSE_PROFILES": "stt,tts",
           "STT_MODEL": "indic-nemotron", "TTS_MODEL": "orpheus", "GPU_DEVICE_IDS": "0"}

    def resolve(extra_files: list[str]) -> dict:
        cmd = ["docker", "compose", "-f", str(ROOT / "compose.model-server.yml")]
        for f in extra_files:
            cmd += ["-f", str(ROOT / f)]
        cmd += ["--project-directory", str(ROOT), "config"]
        out = subprocess.run(cmd, capture_output=True, text=True, env=env)
        assert out.returncode == 0, out.stderr
        return yaml.safe_load(out.stdout)

    base = resolve(["stt/indic-nemotron/compose.extra.yml"])
    with_grpc = resolve(["stt/indic-nemotron/compose.extra.yml", "compose.grpc.yml"])

    for name, svc in base["services"].items():
        assert with_grpc["services"].get(name) == svc, (
            f"attaching compose.grpc.yml changed the resolved `{name}` service. "
            f"The overlay must only add stt-grpc; anything else is a change "
            f"every adopter would inherit."
        )
    added = set(with_grpc["services"]) - set(base["services"])
    assert added == {"stt-grpc"}, f"the overlay added {added}, expected just stt-grpc"


def test_the_facade_folder_is_hidden_from_the_model_menu_and_the_catalogue():
    """`_grpc` is not a model. The leading underscore is what says so, in both
    places that enumerate model folders -- setup.sh's menu and the catalogue
    test. If either stopped honouring it, an operator would be offered a proxy
    as a speech model."""
    setup = (ROOT / "setup.sh").read_text(encoding="utf-8")
    assert "-not -name '_*'" in setup, \
        "setup.sh no longer excludes _* folders; stt/_grpc would appear in the menu"
    catalogue = (ROOT / "tests" / "test_catalogue.py").read_text(encoding="utf-8")
    assert 'startswith(("_", "."))' in catalogue, \
        "the catalogue test no longer exempts _* folders; stt/_grpc would need an entry"


def test_it_publishes_on_localhost_by_default():
    """The gateway binds 0.0.0.0 with no auth, which the review flagged. A
    second unauthenticated port on every interface would repeat that."""
    overlay = yaml.safe_load((ROOT / "compose.grpc.yml").read_text(encoding="utf-8"))
    ports = overlay["services"]["stt-grpc"]["ports"]
    assert any("127.0.0.1" in str(p) for p in ports), \
        f"stt-grpc does not default to a localhost bind: {ports}"


# ----------------------------------------------------------- translation (needs grpc)

grpc = pytest.importorskip("grpc", reason="grpcio not installed")
pytest.importorskip("grpc_tools", reason="grpcio-tools not installed")
pytest.importorskip("grpc_health.v1", reason="grpcio-health-checking not installed")
websockets = pytest.importorskip("websockets")


@pytest.fixture(scope="module")
def facade(tmp_path_factory):
    """Generate the stubs and import the server. Stubs are built here rather
    than committed, for the same reason the Dockerfile builds them: generated
    code checked in beside a .proto drifts from it and nothing notices."""
    from grpc_tools import protoc

    out = tmp_path_factory.mktemp("pb")
    rc = protoc.main(["protoc", f"-I{FACADE}", f"--python_out={out}",
                      f"--grpc_python_out={out}", str(FACADE / "asr.proto")])
    assert rc == 0, "protoc failed on asr.proto"
    sys.path.insert(0, str(out))
    sys.path.insert(0, str(FACADE))
    for mod in ("asr_pb2", "asr_pb2_grpc", "server"):
        sys.modules.pop(mod, None)
    import asr_pb2
    import asr_pb2_grpc
    import server
    return server, asr_pb2, asr_pb2_grpc


@pytest.fixture
async def stub_model():
    """A WebSocket that speaks the model's protocol and records what it saw."""
    seen: dict = {"languages": [], "audio_bytes": 0, "actions": []}

    async def handler(ws):
        path = getattr(getattr(ws, "request", None), "path", "") or ""
        lang = path.partition("language=")[2].partition("&")[0] or "?"
        seen["languages"].append(lang)
        if lang.startswith("zz"):
            # How the real model refuses: an error frame naming what it accepts,
            # then a 1011 close.
            await ws.send(json.dumps({"error": f"Unsupported language '{lang}'. "
                                               f"Supported: ['bhb', 'en', 'hi']"}))
            await ws.close(code=1011, reason="internal error")
            return
        await ws.send(json.dumps({
            "session_id": "stub-1", "status": "ready", "language": lang,
            "model_chunk_ms": 320, "wire_chunk_ms": 160,
            "expected_sample_rate": 16000, "build_id": "stub",
        }))
        async for msg in ws:
            if isinstance(msg, (bytes, bytearray)):
                seen["audio_bytes"] += len(msg)
                continue
            action = json.loads(msg).get("action")
            seen["actions"].append(action)
            if action == "flush_eos":
                await ws.send(json.dumps({"text": "नम", "is_final": False,
                                          "latency_ms": 11.0, "language": lang}))
                await ws.send(json.dumps({"text": "नमस्ते", "is_final": True,
                                          "latency_ms": 12.5, "language": lang}))

    server = await websockets.serve(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    yield f"ws://127.0.0.1:{port}/v1/asr/ws", seen
    server.close()
    await server.wait_closed()


@pytest.fixture
async def channel(facade, stub_model):
    srv_mod, _, asr_pb2_grpc = facade
    url, _ = stub_model
    srv_mod.STT_WS_URL = url

    server = grpc.aio.server()
    asr_pb2_grpc.add_AsrServicer_to_server(srv_mod.AsrServicer(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as ch:
        yield ch
    await server.stop(None)


def _requests(asr_pb2, language="hi", frames=3, **cfg):
    async def gen():
        yield asr_pb2.StreamingRequest(config=asr_pb2.StreamingConfig(
            language=language, sample_rate_hz=16000,
            encoding=asr_pb2.LINEAR16, **cfg))
        for _ in range(frames):
            yield asr_pb2.StreamingRequest(audio=b"\x00\x01" * 2560)
    return gen()


@pytest.mark.asyncio
async def test_a_stream_yields_started_then_interims_then_a_final(facade, channel, stub_model):
    srv_mod, asr_pb2, asr_pb2_grpc = facade
    _, seen = stub_model
    stub = asr_pb2_grpc.AsrStub(channel)

    events = [e async for e in stub.StreamingRecognize(_requests(asr_pb2))]
    kinds = [e.WhichOneof("event") for e in events]

    assert kinds[0] == "started", f"first event was {kinds[0]}, expected the session header"
    assert events[0].started.expected_sample_rate_hz == 16000
    assert events[0].started.model_chunk_ms == 320

    transcripts = [e.transcript for e in events if e.WhichOneof("event") == "transcript"]
    assert [t.is_final for t in transcripts] == [False, True], \
        "expected one interim then one final"
    assert transcripts[-1].text == "नमस्ते"
    assert transcripts[-1].latency_ms == pytest.approx(12.5)

    # Half-close must become flush_eos, or the turn never ends -- the exact
    # failure this repo already fixed once on the WebSocket path.
    assert "flush_eos" in seen["actions"]
    assert seen["audio_bytes"] == 3 * 5120


@pytest.mark.asyncio
async def test_interims_can_be_turned_off(facade, channel):
    srv_mod, asr_pb2, asr_pb2_grpc = facade
    stub = asr_pb2_grpc.AsrStub(channel)
    events = [e async for e in stub.StreamingRecognize(
        _requests(asr_pb2, disable_interim_results=True))]
    finals = [e.transcript.is_final for e in events if e.WhichOneof("event") == "transcript"]
    assert finals == [True], f"interims leaked through: {finals}"


@pytest.mark.asyncio
async def test_a_bcp47_region_is_stripped_before_it_reaches_the_model(facade, channel, stub_model):
    """Riva-shaped clients send hi-IN. The model's prompt dictionary keys are
    bare codes, so the region has to go -- and Bhili has no region anyone
    agrees on, hence bhb and bhb-IN both landing on bhb."""
    srv_mod, asr_pb2, asr_pb2_grpc = facade
    _, seen = stub_model
    stub = asr_pb2_grpc.AsrStub(channel)
    [e async for e in stub.StreamingRecognize(_requests(asr_pb2, language="bhb-IN"))]
    assert seen["languages"] == ["bhb"], f"model saw {seen['languages']}"


@pytest.mark.asyncio
@pytest.mark.parametrize("cfg,expect", [
    ({"language": ""}, "language is required"),
    ({"language": "hi", "sample_rate_hz": 8000}, "sample_rate_hz must be 16000"),
])
async def test_bad_config_is_refused_rather_than_guessed(facade, channel, cfg, expect):
    """No auto-detection and no resampling: both are silent-wrongness risks, so
    they are INVALID_ARGUMENT with a reason, never a default."""
    srv_mod, asr_pb2, asr_pb2_grpc = facade
    stub = asr_pb2_grpc.AsrStub(channel)

    async def gen():
        base = {"language": "hi", "sample_rate_hz": 16000, "encoding": asr_pb2.LINEAR16}
        yield asr_pb2.StreamingRequest(config=asr_pb2.StreamingConfig(**{**base, **cfg}))

    with pytest.raises(grpc.aio.AioRpcError) as exc:
        [e async for e in stub.StreamingRecognize(gen())]
    assert exc.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert expect in exc.value.details()


@pytest.mark.asyncio
async def test_audio_before_config_is_refused(facade, channel):
    srv_mod, asr_pb2, asr_pb2_grpc = facade
    stub = asr_pb2_grpc.AsrStub(channel)

    async def gen():
        yield asr_pb2.StreamingRequest(audio=b"\x00\x01" * 8)

    with pytest.raises(grpc.aio.AioRpcError) as exc:
        [e async for e in stub.StreamingRecognize(gen())]
    assert exc.value.code() == grpc.StatusCode.INVALID_ARGUMENT
    assert "first message must be a StreamingConfig" in exc.value.details()


@pytest.mark.asyncio
async def test_a_model_that_is_still_loading_is_unavailable_not_internal(facade):
    """Minutes of checkpoint restore is the normal state after a start. A caller
    has to be able to tell "retry shortly" from "this is broken"."""
    srv_mod, asr_pb2, asr_pb2_grpc = facade
    srv_mod.STT_WS_URL = "ws://127.0.0.1:1/v1/asr/ws"
    srv_mod.OPEN_TIMEOUT_S = 1.0

    server = grpc.aio.server()
    asr_pb2_grpc.add_AsrServicer_to_server(srv_mod.AsrServicer(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as ch:
            stub = asr_pb2_grpc.AsrStub(ch)
            with pytest.raises(grpc.aio.AioRpcError) as exc:
                [e async for e in stub.StreamingRecognize(_requests(asr_pb2))]
    finally:
        await server.stop(None)
    assert exc.value.code() == grpc.StatusCode.UNAVAILABLE


def test_the_proto_offers_no_auto_language_and_no_resample_knob(facade):
    """Two decisions worth pinning in the schema, because both are places a
    future contributor would reasonably add a convenience that silently
    degrades transcripts: an `auto` language (the vocabulary is sliced per
    language, so an unsliced decode emits cross-script nonsense) and a
    resample flag (a quality decision hidden in a transport component).

    Checked against the DECLARED FIELD NAMES, with comments stripped. A
    substring search over the whole file matches the comments that explain why
    these are absent -- which is how the same guard in
    test_engine_env_surface.py used to pass on a variable that a comment merely
    mentioned.
    """
    import re

    code = "\n".join(
        line.split("//", 1)[0]
        for line in (FACADE / "asr.proto").read_text(encoding="utf-8").splitlines()
    )
    fields = set(re.findall(r"^\s*(?:optional\s+|repeated\s+)?[\w.]+\s+(\w+)\s*=\s*\d+\s*;",
                            code, re.MULTILINE))
    assert fields, "parsed no fields out of asr.proto -- the regex has rotted"

    for banned in ("resample", "auto_language", "auto_detect", "detect_language"):
        offenders = {f for f in fields if banned in f}
        assert not offenders, f"asr.proto declares {offenders}, which reopens a closed decision"
    # `language` itself must stay required-by-validation, not optional-with-default.
    assert "language" in fields


@pytest.mark.asyncio
async def test_a_language_the_model_refuses_is_invalid_argument_not_unknown(facade, channel):
    """The model answers a bad language with {"error": ...} and a 1011 close.

    That message is the useful one -- it lists every language it accepts. It used
    to be yielded as a Warning, and the 1011 then raised ConnectionClosedError
    out of the servicer, so a caller got

        UNKNOWN: Unexpected <class 'websockets.exceptions.ConnectionClosedError'>

    with the real explanation in an event it had no reason to read. Reproduced
    against the live model on ace-h200 with fr-FR and zz.
    """
    srv_mod, asr_pb2, asr_pb2_grpc = facade
    stub = asr_pb2_grpc.AsrStub(channel)

    with pytest.raises(grpc.aio.AioRpcError) as exc:
        [e async for e in stub.StreamingRecognize(_requests(asr_pb2, language="zz"))]

    assert exc.value.code() == grpc.StatusCode.INVALID_ARGUMENT, \
        f"got {exc.value.code().name}; a refused request must not look like a transport fault"
    details = exc.value.details()
    assert "Unsupported language" in details, details
    assert "Supported:" in details, "the model's list of valid codes did not reach the caller"
    assert "websockets" not in details, "an internal exception type leaked to the caller"


@pytest.mark.asyncio
async def test_commit_ends_a_turn_without_ending_the_call(facade, channel, stub_model):
    """With ASR_VAD=0 nothing else finalises a transcript, so a caller doing its
    own endpointing -- which is why the VAD is off -- depends on this."""
    srv_mod, asr_pb2, asr_pb2_grpc = facade
    _, seen = stub_model
    stub = asr_pb2_grpc.AsrStub(channel)

    async def gen():
        yield asr_pb2.StreamingRequest(config=asr_pb2.StreamingConfig(
            language="hi", sample_rate_hz=16000, encoding=asr_pb2.LINEAR16))
        yield asr_pb2.StreamingRequest(audio=b"\x00\x01" * 2560)
        yield asr_pb2.StreamingRequest(commit=asr_pb2.CommitTurn())
        yield asr_pb2.StreamingRequest(audio=b"\x00\x01" * 2560)

    finals = 0
    async for ev in stub.StreamingRecognize(gen()):
        if ev.WhichOneof("event") == "transcript" and ev.transcript.is_final:
            finals += 1

    # One from the explicit commit, one from the half-close at the end.
    assert finals >= 2, f"only {finals} final(s); a committed turn did not finalise"
    assert seen["actions"].count("flush_eos") >= 2, seen["actions"]
