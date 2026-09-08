"""Demo pages, one per slot, and the catalogue routes they read.

Every model ships its own demo page and serves it at `/demo` on its own port.
The gateway only forwards. That worked while STT was the only slot with a page;
adding one to TTS broke two assumptions at once.

**Two slots cannot both own `/demo`.** STT had it because it was first, which is
not a reason. Each slot now has `/demo/<kind>`, and `/demo` redirects when only
one slot is filled -- so a URL made when STT was the only demo keeps working --
and lists them when more than one is.

**Two slots publish `/v1/languages` with different shapes.** STT answers with the
checkpoint's language roster; Orpheus answers with a voice roster. The same path
meaning different things depending on what happens to be deployed is the kind of
ambiguity that is invisible until someone swaps a model. Catalogue routes are now
reachable under their slot, and a page asks for its own.

The sharp edge in all of this is route ordering: a catch-all declared before a
named route silently swallows it, and the symptom is a working endpoint quietly
returning something else's answer.
"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "gateway"))

from app.config import Settings, Upstream  # noqa: E402
from app.main import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

DEFAULT_URL = {"stt": "http://stt:8001", "tts": "http://tts:8002", "llm": "http://llm:8003"}


def settings(**models) -> Settings:
    """A Settings with the named slots filled and the rest empty."""
    def slot(kind):
        model = models.get(kind + "_model", "")
        return Upstream(kind, DEFAULT_URL[kind] if model else "", model)
    return Settings(slot("stt"), slot("tts"), slot("llm"))


def client(**models):
    from fastapi.testclient import TestClient
    return TestClient(create_app(settings(**models)))


def paths(app) -> list[str]:
    return [getattr(r, "path", "") for r in app.routes]


# ------------------------------------------------------------- /demo routing

def test_one_slot_keeps_the_url_that_already_exists():
    """The tunnel URL people are using today ends at /demo. It must not 404
    because a second slot gained a page."""
    r = client(stt_model="indic-transcribe").get("/demo", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/demo/stt"


def test_several_slots_get_an_index_rather_than_a_guess():
    r = client(stt_model="indic-transcribe", tts_model="orpheus").get("/demo")
    assert r.status_code == 200
    assert "/demo/stt" in r.text and "/demo/tts" in r.text


def test_no_slots_says_so_instead_of_redirecting_nowhere():
    r = client().get("/demo", follow_redirects=False)
    assert r.status_code == 503
    assert "STT_MODEL" in r.text, "the error does not say how to fix it"


def test_an_unknown_slot_names_the_real_ones():
    """`/demo/sst` is a typo someone will make. Answering 404 with nothing else
    sends them to read the gateway source."""
    r = client(stt_model="indic-transcribe").get("/demo/nope")
    assert r.status_code == 404
    detail = r.json()["detail"]
    assert "stt" in detail and "tts" in detail and "llm" in detail


def test_a_slot_with_no_model_is_unavailable_not_missing():
    """404 would say the route does not exist; it does, and nothing fills it."""
    r = client(stt_model="indic-transcribe").get("/demo/tts")
    assert r.status_code == 503, f"expected 503 for an empty slot, got {r.status_code}"


# --------------------------------------------------------- route precedence

def test_the_catch_all_is_declared_last():
    """A catch-all above a named route swallows it, and the symptom is not an
    error -- it is the wrong upstream answering, which looks like a model bug."""
    app = create_app(settings(stt_model="indic-transcribe", tts_model="orpheus"))
    declared = paths(app)
    catch_all = declared.index("/{slot}/{path:path}")
    for named in ("/health", "/models", "/v1/models", "/demo", "/demo/{slot}",
                  "/v1/languages", "/v1/audio/transcriptions", "/v1/audio/speech",
                  "/v1/chat/completions"):
        assert named in declared, f"{named} is gone"
        assert declared.index(named) < catch_all, \
            f"{named} is declared after the catch-all and will never be reached"


def test_the_websocket_catch_all_is_declared_after_the_named_sockets():
    app = create_app(settings(stt_model="indic-transcribe"))
    declared = paths(app)
    ws_catch_all = len(declared) - 1 - declared[::-1].index("/{slot}/{path:path}")
    for named in ("/v1/realtime", "/v1/asr/ws"):
        assert declared.index(named) < ws_catch_all, \
            f"{named} would be handled by the generic relay instead of its own"


def test_the_passthrough_reads_but_does_not_write():
    """The models publish mutating routes -- indic-transcribe has
    /admin/reset_stats -- and this gateway is the one port the stack publishes.
    A method-agnostic catch-all would put those on the internet."""
    app = create_app(settings(stt_model="indic-transcribe"))
    for r in app.routes:
        if getattr(r, "path", "") == "/{slot}/{path:path}":
            methods = set(getattr(r, "methods", []) or [])
            if not methods:
                continue                       # the websocket entry
            assert methods <= {"GET", "HEAD"}, \
                f"the slot passthrough accepts {sorted(methods)}; admin routes would be reachable"


def test_unprefixed_v1_languages_still_reaches_stt():
    """It is in use. Renaming it to tidy the scheme would break a caller to fix
    nothing -- the ambiguity is solved by the prefixed routes existing."""
    app = create_app(settings(stt_model="indic-transcribe", tts_model="orpheus"))
    assert "/v1/languages" in paths(app)


# ------------------------------------------------------------- the TTS page

TTS_DEMO = ROOT / "tts" / "orpheus" / "static" / "demo.html"


@pytest.mark.skipif(not TTS_DEMO.is_file(), reason="orpheus not present in this checkout")
def test_the_tts_page_names_no_model_and_no_voice():
    """Same rule as the STT page: whichever model fills the slot says who it is
    and what it can say. A hardcoded voice list is wrong for every other model,
    and wrong for this one the moment its roster changes."""
    html = TTS_DEMO.read_text(encoding="utf-8")
    for name in ("Orpheus", "orpheus"):
        assert name not in html, f"the page hardcodes {name!r}"
    assert "/v1/languages" in html, "the voice roster is not read from the model"
    assert "/v1/styles" in html, "styles are not read from the model"


@pytest.mark.skipif(not TTS_DEMO.is_file(), reason="orpheus not present in this checkout")
def test_the_tts_page_works_served_direct_or_proxied():
    """Served at /demo it must call /v1/...; served at /demo/tts it must call
    /tts/v1/.... Getting this wrong fails only through the gateway, which is the
    path nobody tests locally."""
    html = TTS_DEMO.read_text(encoding="utf-8")
    assert "(stt|tts|llm)" in html, \
        "the page does not work out which slot prefix it is being served under"
    assert "API + '/v1/languages'" in html, \
        "a catalogue fetch is not slot-prefixed and will 404 behind the gateway"


@pytest.mark.parametrize("page", sorted((ROOT / "stt").glob("*/static/realtime.html")) or [None])
def test_the_stt_page_learned_the_same_trick(page):
    """It was written when /demo was unprefixed. Left alone it still works, but
    its /health call would reach the gateway's health rather than the model's,
    so the page could not name the model that is answering."""
    if page is None:
        pytest.skip("no STT demo in this checkout")
    html = page.read_text(encoding="utf-8")
    assert "(stt|tts|llm)" in html, "the STT page is not slot-aware"
    assert "fetch('/health')" not in html, \
        "an unprefixed /health reaches the gateway, not the model behind it"


def test_the_two_demo_pages_are_not_the_same_file():
    """Guarding the accident that has already happened twice in this repo: a new
    page dropped in over an existing one. STT and TTS pages are different files
    with different jobs, and neither should quietly become the other."""
    if not TTS_DEMO.is_file():
        pytest.skip("orpheus not present in this checkout")
    stt = sorted((ROOT / "stt").glob("*/static/realtime.html"))
    if not stt:
        pytest.skip("no STT demo in this checkout")
    assert TTS_DEMO.read_text(encoding="utf-8") != stt[0].read_text(encoding="utf-8")


# ------------------------------------------------- against real upstreams

def test_each_slot_gets_its_own_answer_from_its_own_model():
    """Route tables can look right and still forward to the wrong place.

    Two stub upstreams that answer the same path differently, so a mix-up shows
    up as the wrong body rather than as a passing test. This is the check that
    the whole slot-prefix scheme was for: `/v1/languages` means one thing under
    /stt and another under /tts, and neither shadows the other.

    Runs the app through its lifespan -- the proxy client is created there, and
    a TestClient built without it fails on `state.http` rather than on routing.
    """
    from conftest import free_port, serve
    from fastapi import FastAPI

    def stub(kind):
        a = FastAPI()
        a.get("/v1/languages")(lambda: {"slot": kind})
        a.get("/demo")(lambda: {"page": kind})
        a.post("/admin/reset_stats")(lambda: {"reset": kind})
        return a

    ps, pt = free_port(), free_port()
    serve(stub("stt"), ps)
    serve(stub("tts"), pt)
    cfg = Settings(Upstream("stt", f"http://127.0.0.1:{ps}", "indic-transcribe"),
                   Upstream("tts", f"http://127.0.0.1:{pt}", "orpheus"),
                   Upstream("llm", "", ""))
    with TestClient(create_app(cfg)) as c:
        assert c.get("/stt/v1/languages").json() == {"slot": "stt"}
        assert c.get("/tts/v1/languages").json() == {"slot": "tts"}
        assert c.get("/v1/languages").json() == {"slot": "stt"}, \
            "the unprefixed route stopped meaning STT"
        assert c.get("/demo/stt").json() == {"page": "stt"}
        assert c.get("/demo/tts").json() == {"page": "tts"}
        assert c.post("/stt/admin/reset_stats").status_code == 405, \
            "the passthrough proxies a mutating route; admin is reachable from outside"

