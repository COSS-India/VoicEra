"""OpenAI Realtime transcription for indic-transcribe.

The slot standardises on one protocol so that switching model cannot change
what a caller receives. Indic-Conformer got there first, by manufacturing
partials on a timer; this model decodes incrementally and already produced
them, so the work was translating envelopes rather than inventing updates.

What has to hold, and what breaks silently if it does not:

* the same delta rule as every other STT model -- whole words, and a revision
  withdraws by advancing content_index rather than patching in place
* one turn ending does not end the stream, and the next turn does not get
  appended onto the last one's content item
* the transport is a parameter, not a copy: both routes run the same turn
  machinery, including the rotation that stops a long stream walking off the
  decoder's position limit into a CUDA fault

The wire is tested in isolation; the route itself is not yet exercised end to
end. See the note at the bottom of this file.
"""
import asyncio
import base64
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
MODEL_DIR = ROOT / "stt" / "indic-transcribe"

needs_model = pytest.mark.skipif(
    not (MODEL_DIR / "realtime_wire.py").is_file(),
    reason="indic-transcribe not present in this checkout",
)

if MODEL_DIR.is_dir():
    sys.path.insert(0, str(MODEL_DIR))


async def recv(ws, timeout: float = 5.0):
    """Every read is bounded: a wire that drops an event never answers, and an
    unbounded read turns that into a hang rather than a failure."""
    return await asyncio.wait_for(ws.recv(), timeout=timeout)


def _append(n_samples: int = 4800) -> str:
    pcm = (np.zeros(n_samples, dtype=np.int16)).tobytes()
    return json.dumps({"type": "input_audio_buffer.append",
                       "audio": base64.b64encode(pcm).decode()})


# --------------------------------------------------------------- the wire

@needs_model
def test_the_client_event_vocabulary_maps_to_the_stream_loops_verbs():
    """The loop must never learn which protocol it is speaking. Both wires
    return the same small vocabulary; only the envelopes differ."""
    from realtime_wire import NativeWire, OpenAIRealtimeWire
    oai = OpenAIRealtimeWire(ws=None)

    kind, payload = oai.parse_text(_append())
    assert kind == "audio" and "pcm" in payload

    assert oai.parse_text(json.dumps({"type": "input_audio_buffer.commit"}))[0] == "commit"
    assert oai.parse_text(json.dumps({"type": "input_audio_buffer.clear"}))[0] == "stop"
    assert oai.parse_text("not json at all")[0] == ""

    native = NativeWire(ws=None)
    assert native.parse_text(json.dumps({"type": "stop"}))[0] == "stop"
    assert native.parse_text("stop")[0] == "stop", "bare-word commands still work"


@needs_model
def test_audio_is_resampled_from_the_rate_the_spec_sends():
    """OpenAI Realtime carries 24 kHz; this engine decodes at 16 kHz. Feeding
    24 kHz samples to a 16 kHz decoder does not error -- it transcribes speech
    that sounds 1.5x too fast, which reads as a bad model rather than a bug."""
    from realtime_wire import OpenAIRealtimeWire
    oai = OpenAIRealtimeWire(ws=None)
    out = oai.decode_audio(np.zeros(2400, dtype=np.int16).tobytes())
    assert len(out) == 1600, f"expected 16 kHz, got {len(out) / 0.1:.0f} Hz"
    assert out.dtype == np.float32


@needs_model
def test_both_models_share_one_delta_rule():
    """Vendored, not imported -- a model folder must stay copyable. Duplication
    is the accepted cost; divergence is not, because a caller switching model
    would then get differently-shaped transcripts from the same slot."""
    conformer = ROOT / "stt" / "indic-conformer" / "realtime_protocol.py"
    transcribe = MODEL_DIR / "realtime_protocol.py"
    if not conformer.is_file():
        pytest.skip("indic-conformer not present in this checkout")
    assert conformer.read_text(encoding="utf-8") == transcribe.read_text(encoding="utf-8"), (
        "the vendored copies of realtime_protocol.py have drifted. Fix one and "
        "copy the file; do not patch a single folder."
    )


# ------------------------------------------------------------- end to end
#
# NOT WRITTEN YET, and the gap is worth naming rather than leaving as an absence.
#
# Everything above tests the wire in isolation: the event vocabulary, the
# resampling, and that the two vendored copies of the delta rule match. What is
# not covered is the route itself -- audio in through a real socket, deltas out,
# a completed event at the turn end -- because that needs the decoder stubbed at
# the seam where app.py loads a real NeMo checkpoint, and that stub does not
# exist here.
#
# So: `/v1/realtime` is written and its wire is tested, and no audio has been
# through it. The first person to run it on hardware is the one who finds out.
#
# The stub wants to replace app.state.engine and app.state.worker with objects
# that emit the same partial/final shape the GPU worker does; tests/stubs/ is
# where the other model's fakes live and is the place for it.


# ------------------------------------------------------------- the demo page

def _stt_models_with(filename: str) -> list[Path]:
    return sorted((ROOT / "stt").glob(f"*/static/{filename}"))


def test_the_realtime_demo_is_vendored_identically():
    """One page, every STT folder, byte for byte.

    It is the cheapest end-to-end check available: point it at either model
    through the gateway's /demo and the same file must behave the same way.
    That only means something if it really is the same file -- a copy that
    drifted would be testing two different pages and proving nothing.
    """
    copies = _stt_models_with("realtime.html")
    assert len(copies) >= 2, f"expected the shared demo in every STT folder, found {copies}"
    first = copies[0].read_text(encoding="utf-8")
    for other in copies[1:]:
        assert other.read_text(encoding="utf-8") == first, (
            f"{other} has drifted from {copies[0]}. Fix one and copy the file."
        )


@pytest.mark.parametrize("page", _stt_models_with("realtime.html") or [None])
def test_the_shared_demo_names_no_model(page):
    """A page served by whichever model fills the slot cannot hardcode one.

    It asks /health who is answering and /v1/languages what they speak, so it
    stays correct across a model swap and across a rename. A hardcoded language
    list is the sharper half: the two models here support 23 and 25 languages,
    so any fixed list is wrong for one of them.
    """
    if page is None:
        pytest.skip("no shared demo in this checkout")
    html = page.read_text(encoding="utf-8")
    for name in ("Indic Conformer", "indic-conformer", "Indic-Transcribe", "indic-transcribe"):
        assert name not in html, f"{page.name} hardcodes the model name {name!r}"
    assert "/v1/languages" in html, "the language list is not read from the model"
    assert "/v1/realtime" in html, "the demo does not speak the slot's protocol"


def test_the_native_demo_was_not_replaced_by_the_shared_one():
    """indic-transcribe ships its own page for its own protocol, and it is the
    only thing that drives /v1/asr/ws by hand.

    Worth pinning because the two files nearly collided: dropping the shared
    page in as `demo.html` would have overwritten upstream's without a trace,
    which is the same accident that cost this repo 522 lines of Orpheus
    documentation once already.
    """
    native = ROOT / "stt" / "indic-transcribe" / "static" / "demo.html"
    if not native.is_file():
        pytest.skip("indic-transcribe not present in this checkout")
    html = native.read_text(encoding="utf-8")
    assert "/v1/asr/ws" in html, "the native demo no longer speaks the native protocol"
    shared = ROOT / "stt" / "indic-transcribe" / "static" / "realtime.html"
    assert html != shared.read_text(encoding="utf-8"), \
        "the shared demo has overwritten the native one"


def _gateway_routes() -> set[str]:
    """The paths the gateway actually serves, read from its source.

    Parsed rather than listed, so this test tracks the gateway instead of a copy
    of it that someone has to remember to update.
    """
    import ast
    main = ROOT / "gateway" / "app" / "main.py"
    tree = ast.parse(main.read_text(encoding="utf-8"))
    paths = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr in ("get", "post", "websocket") and dec.args
                    and isinstance(dec.args[0], ast.Constant)):
                paths.add(dec.args[0].value)
    return paths


@pytest.mark.parametrize("page", _stt_models_with("realtime.html") or [None])
def test_every_route_the_demo_calls_is_one_the_gateway_forwards(page):
    """The page fetches relatively, so served through the gateway it asks the
    gateway -- and an unforwarded route fails silently.

    This is not hypothetical. /v1/languages was missing here, so the fetch 404d,
    the picker kept its four-language fallback, and a 25-language model looked
    like a 4-language one on a page that reported no error at all. Every failure
    of this shape is silent by construction: the page degrades on purpose so it
    stays usable when something is already wrong, which means the gateway is the
    only place the gap can be caught.
    """
    if page is None:
        pytest.skip("no shared demo in this checkout")
    import re
    html = page.read_text(encoding="utf-8")
    # Both spellings: a bare fetch('/x'), and fetch(API + '/x') once the page
    # learned to prefix itself with its slot when served through the gateway.
    called = {m.split("?")[0] for m in re.findall(r"fetch\(\s*'(/[^']+)'", html)}
    called |= {m.split("?")[0] for m in re.findall(r"fetch\(\s*API \+ '(/[^']+)'", html)}
    called |= {m.split("?")[0] for m in re.findall(r"'(/v1/[^']+)'", html)}
    assert called, "found no routes in the demo page -- the extraction has drifted"
    missing = sorted(called - _gateway_routes())
    assert not missing, (
        f"{page.name} calls {missing}, which gateway/app/main.py does not serve. "
        "Through the gateway those 404 and the page degrades without saying so."
    )


# ------------------------------------------------------------ the language

@needs_model
def test_a_session_update_says_which_language_it_wants():
    """Both nestings, and the region tag normalised away.

    "ta-IN" reaching the engine as "ta-IN" is a 400 on a request that is
    perfectly well formed, and indic-conformer accepts it -- so the same client
    against the same slot would work or fail depending on which model is loaded.
    """
    from realtime_wire import OpenAIRealtimeWire as W

    current = {"session": {"audio": {"input": {"transcription": {"language": "kn"}}}}}
    older = {"session": {"input_audio_transcription": {"language": "kn"}}}
    assert W.requested_language(current) == "kn"
    assert W.requested_language(older) == "kn"
    assert W.requested_language({"session": {"audio": {"input": {
        "transcription": {"language": "ta-IN"}}}}}) == "ta"
    assert W.requested_language({"session": {}}) is None
    assert W.requested_language({}) is None
    assert W.requested_language({"session": {"audio": {"input": {
        "transcription": {"model": "x"}}}}}) is None, "a model-only update is not a language"


@needs_model
def test_both_stt_models_read_one_session_update_the_same_way():
    """The slot's promise is that swapping model cannot change what a caller gets.

    This is the case that broke it: indic-conformer applied the language from
    session.update, indic-transcribe acknowledged the event and kept decoding in
    its configured default. A caller asking for Kannada got Kannada from one
    model and Devanagari from the other, with no error from either.
    """
    conformer = ROOT / "stt" / "indic-conformer" / "realtime_ws.py"
    if not conformer.is_file():
        pytest.skip("indic-conformer not present in this checkout")
    import types
    sys.path.insert(0, str(conformer.parent))
    from realtime_wire import OpenAIRealtimeWire
    from realtime_ws import RealtimeProtocol

    evt = {"session": {"audio": {"input": {"transcription": {"language": "kn-IN"}}}}}
    theirs = RealtimeProtocol._parse_language(
        types.SimpleNamespace(_session=types.SimpleNamespace(model=None)), evt)
    assert OpenAIRealtimeWire.requested_language(evt) == theirs == "kn"


@needs_model
def test_the_decode_language_follows_session_update_rather_than_the_handshake():
    """Read from app.py itself, because the failure is silent by construction.

    A wrong language does not raise -- the checkpoint transcribes confidently in
    the wrong script. So the only evidence that the handler does anything is that
    it validates the request and rebinds the language every later turn is created
    from. Acknowledging without rebinding is the bug, and it looks identical to
    working from the outside.
    """
    import ast
    src = (MODEL_DIR / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    run = next(n for n in ast.walk(tree)
               if isinstance(n, ast.AsyncFunctionDef) and n.name == "_run_stream")
    body = ast.get_source_segment(src, run) or ""

    assert 'lang=state["lang"]' in body, (
        "create_session is still passed the language the socket opened with, so a "
        "mid-stream change cannot reach the decoder"
    )
    branch = body.split('kind == "session.update"', 1)
    assert len(branch) == 2, "no session.update branch in _run_stream"
    handler = branch[1].split("if pcm is not None", 1)[0]
    assert "validate_request" in handler, \
        "session.update accepts any language without checking the checkpoint serves it"
    assert 'state["lang"] = ' in handler, \
        "session.update is acknowledged without changing the decode language"


@pytest.mark.parametrize("page", _stt_models_with("realtime.html") or [None])
def test_the_demo_configures_itself_the_way_the_spec_says(page):
    """The demo is the standing evidence that a spec-only client works here.

    The server also accepts `?language=`, and for a while the page used it.
    That made the page pass while telling us nothing: a client built from the
    published protocol has no such parameter, and the question this demo exists
    to answer is whether that client gets the right transcript.
    """
    if page is None:
        pytest.skip("no shared demo in this checkout")
    html = page.read_text(encoding="utf-8")
    assert "?intent=transcription" in html
    assert "language=' + encodeURIComponent" not in html, \
        "the demo is back to configuring language outside the protocol"
    assert "'session.update'" in html, "the demo never configures the session"
    assert "'session.updated'" in html, \
        "the demo does not wait for the server to acknowledge before sending audio"


# ------------------------------------------------------- the delta rule

def _emitter(**kw):
    from realtime_protocol import DeltaEmitter
    return DeltaEmitter(**kw)


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


async def _drive(snapshots, step=0.05, final=None, debounce_s=0.20):
    clock = _Clock()
    em, events = _emitter(debounce_s=debounce_s, clock=clock), []

    async def send(e):
        events.append(e)

    for snap in snapshots:
        await em.update(snap, send)
        clock.t += step
    if final is not None:
        await em.completed(final, send)
    return events


def _deltas(events):
    return [e for e in events if e["type"].endswith(".delta")]


def _concatenated(events):
    """What a consumer doing the obvious thing assembles."""
    return "".join(e["delta"] for e in _deltas(events)).strip()


@needs_model
def test_a_revised_word_never_reaches_the_wire():
    """The case the whole delta rule exists for, judged the way a client judges it.

    The decoder hears "नम" and resolves it to "नमस्ते". Emitting the first and
    then correcting it requires the consumer to know how we signal a
    correction. Not emitting it until it is settled requires nothing.
    """
    events = asyncio.run(_drive(["नम", "नमस्ते", "नमस्ते दुनिया"],
                                step=0.05, final="नमस्ते दुनिया"))
    assert _concatenated(events) == "नमस्ते दुनिया", \
        "a plain concatenation of the deltas is not the transcript"
    assert {e["content_index"] for e in _deltas(events)} == {0}, \
        "content_index moved, which means a revision went out and was withdrawn"


@needs_model
def test_a_single_word_utterance_appears_before_the_turn_ends():
    """The reason the trailing word is debounced rather than simply held.

    Holding every unsettled word until a successor arrives is trivially
    append-only and unusable: say one word and the screen stays empty until you
    stop speaking. The debounce releases it once it has stopped changing.
    """
    events = asyncio.run(_drive(["hello"] * 6, step=0.05))
    assert _concatenated(events) == "hello", "the only word never arrived"


@needs_model
def test_the_held_word_is_flushed_by_the_completed_event():
    """Otherwise the last word of every turn reaches a delta-only consumer only
    inside `completed` -- a different shape from every other word, and the kind
    of difference that surfaces as one missing word in someone else's UI."""
    events = asyncio.run(_drive(["a", "a b"], step=0.01, final="a b"))
    assert _concatenated(events) == "a b"
    final = [e for e in events if e["type"].endswith(".completed")]
    assert len(final) == 1 and final[0]["transcript"] == "a b"


@needs_model
def test_the_wire_invents_no_server_events():
    """Every event type this server sends, checked against the published set.

    `session.closed` was here and is not in the spec. It was harmless -- a
    client ignores what it does not recognise -- but an invented event is a
    thing a reader looks up and cannot find, and indic-conformer never sent it,
    so one slot ended a stream two different ways depending on the model.
    """
    import ast
    SPEC = {
        "session.created", "session.updated", "error",
        "input_audio_buffer.committed", "input_audio_buffer.cleared",
        "input_audio_buffer.speech_started", "input_audio_buffer.speech_stopped",
        "conversation.item.input_audio_transcription.delta",
        "conversation.item.input_audio_transcription.completed",
        "conversation.item.input_audio_transcription.failed",
    }
    sent = set()
    for name in ("realtime_wire.py", "realtime_protocol.py"):
        tree = ast.parse((MODEL_DIR / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # {"type": "...."} in a payload being sent
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values, strict=True):
                    if (isinstance(k, ast.Constant) and k.value == "type"
                            and isinstance(v, ast.Constant)
                            and isinstance(v.value, str) and "." in v.value):
                        sent.add(v.value)
    invented = sorted(sent - SPEC - {"audio/pcm"})
    assert not invented, (
        f"{invented} are not OpenAI Realtime server events. Either the spec "
        f"gained them and this set is stale, or we made them up."
    )

