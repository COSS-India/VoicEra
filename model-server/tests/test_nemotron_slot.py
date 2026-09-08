"""indic-nemotron: vendored whole, configured entirely from outside.

This folder is the first one that is *purely* a copy-in. Every file in it except
`compose.extra.yml`, `fetch.sh` and `.env.example` is upstream's, byte for byte,
and the tests below exist to keep it that way -- because the pressure to "just
fix that one line" in a vendored file is constant, and the cost only shows up
later, when upstream pushes again and the sync is a merge conflict.

So the two things this file pins are:

  * the vendored files are untouched, and
  * everything the deployment needs to change about how the model runs is
    reachable from the overlay.

The second is what makes the first possible. Upstream binds port 8000 and serves
its demo at `/`; neither matches the slot convention, and both are handled by a
variable rather than an edit.

It also pins the three env-surface defects found on the way in, because each one
is silent: a wrong value that produces working-but-worse behaviour, which is the
only kind this repo has ever actually shipped.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
FOLDER = ROOT / "stt" / "indic-nemotron"

pytestmark = pytest.mark.skipif(
    not FOLDER.is_dir(), reason="indic-nemotron not in this checkout")

#: Files the folder owns. Everything else in it is upstream's.
#:
#: Upstream's README is kept as UPSTREAM-README.md and ours is README.md --
#: the convention indic-transcribe and orpheus already use, so their text stays
#: unedited and a re-push from upstream is a clean replace rather than a merge.
OURS = {"compose.extra.yml", "fetch.sh", ".env.example", "README.md"}

#: What upstream shipped, with the checksum it shipped as.
#:
#: Recorded rather than merely listed. Presence proves nothing -- the failure
#: mode is a one-line edit inside a vendored file, which leaves every filename
#: exactly where it was. Regenerate these ONLY when deliberately taking a new
#: upstream push, and in that commit and no other.
VENDORED_MD5 = {
    ".dockerignore": "05e12d6b94f313e2e82f18e98923e695",
    ".gitignore": "97b3bb55f0d5cbc7f4c43ff00b9bb755",
    "Dockerfile": "9ebcfa1d8f28cba68f9bf3dd4a7b5622",
    "UPSTREAM-README.md": "2567e2dfd956ddf3c119a04bcb3e3264",
    "asr_engine.py": "2586e3d086f8a4c079f5e44418f7977c",
    "audio_io.py": "14a0921f46471306a75f5a3787c82fa1",
    "openai_api.py": "85c9a2560c680effb86166ea018053e8",
    "server.py": "e669ffbcf2cd929080b149b985e1f9ed",
    "session.py": "50a12df5b8eec2ccb8f9065c0cb8c66d",
    "static/audio-processor.js": "9e49c521ae5d19b29b521412cd2a260d",
    "static/index.html": "8e895c0c98820d83e32d4ddffdb00228",
}
VENDORED = set(VENDORED_MD5) | {"docker-compose.yml"}


def overlay() -> dict:
    return yaml.safe_load((FOLDER / "compose.extra.yml").read_text(encoding="utf-8"))


def stt_env() -> dict:
    return overlay()["services"]["stt"]["environment"]


def source(name: str) -> str:
    return (FOLDER / name).read_text(encoding="utf-8")


# ------------------------------------------- the folder is a copy, not a fork

def test_every_upstream_file_is_present():
    missing = {f for f in VENDORED if not (FOLDER / f).is_file()}
    assert not missing, f"vendored files missing from the folder: {sorted(missing)}"


def test_no_vendored_file_has_been_edited():
    """The check the whole folder rests on.

    Byte comparison, because the edit that matters is one line deep inside a
    file whose name has not changed -- a hardcoded port, a tweaked default, a
    "quick fix" that becomes a merge conflict on the next upstream push and
    hides a real change in a diff full of ours.

    `docker-compose.yml` is excluded only because it is unused here; it is still
    upstream's and still should not be edited.
    """
    import hashlib
    drifted = []
    for name, want in sorted(VENDORED_MD5.items()):
        got = hashlib.md5((FOLDER / name).read_bytes()).hexdigest()
        if got != want:
            drifted.append(f"{name} ({got} != {want})")
    assert not drifted, (
        "vendored files have been edited: " + "; ".join(drifted) +
        ". Revert them and express the change in compose.extra.yml instead. If "
        "this is a deliberate upstream update, regenerate VENDORED_MD5 in that "
        "commit alone."
    )


def test_we_have_not_edited_the_model_server():
    """The whole slot design rests on this. A model is a folder you copy in; the
    moment we patch one, every push from upstream is a merge conflict, and a
    real change hides in a diff full of ours.

    Checked by content, not by mtime: the two things we needed to change --
    the port and the demo path -- are the exact two a hurried person would
    "just fix here", so they are the two worth pinning.
    """
    server = source("server.py")
    assert "port=8000" in server, (
        "server.py no longer binds 8000. If that was to fit the slot's 8001, "
        "revert it -- the overlay sets STT_UPSTREAM instead, which is what the "
        "gateway's override variable is for."
    )
    assert '@app.get("/")' in server, (
        "the demo route moved off `/`. The gateway reaches it via STT_DEMO_PATH; "
        "upstream's file should not have been touched."
    )


def test_our_own_files_are_the_only_additions():
    present = set()
    for p in FOLDER.rglob("*"):
        if p.is_file() and "__pycache__" not in p.parts and "models" not in p.parts:
            present.add(p.relative_to(FOLDER).as_posix())
    unexplained = present - VENDORED - OURS
    assert not unexplained, (
        f"files in the folder that are neither upstream's nor the slot's: "
        f"{sorted(unexplained)}. If one of them patches upstream behaviour, it "
        f"belongs in compose.extra.yml instead."
    )


# ------------------------------------------------- the values we must declare

def test_the_attention_context_is_declared():
    """The sixth instance of this bug in this repo, and the most expensive.

    asr_engine.py:82 defaults ASR_ATT_CONTEXT to "96,7" -- 640 ms. Upstream's
    own docker-compose.yml overrides it to 96,3 -- 320 ms -- and we do not use
    their compose. Leaving it unset therefore doubles the latency, and presents
    as the model being slow rather than as a line nobody wrote.
    """
    raw = str(stt_env()["ASR_ATT_CONTEXT"])
    assert "96,3" in raw, f"ASR_ATT_CONTEXT is {raw!r}; expected a 96,3 default"

    engine = source("asr_engine.py")
    assert 'ASR_ATT_CONTEXT", "96,7"' in engine, (
        "upstream's code default is no longer 96,7 -- re-check what leaving this "
        "undeclared would now give, and whether 96,3 is still the right choice"
    )


def test_the_undeclared_vad_margin_is_declared_here():
    """session.py reads ASR_VAD_MARGIN_DB; upstream declares it nowhere -- not in
    their compose, not in their README. An operator tuning endpointing cannot
    find a variable that is not written down."""
    assert "ASR_VAD_MARGIN_DB" in source("session.py"), \
        "upstream no longer reads this; the declaration below may be dead"
    assert "ASR_VAD_MARGIN_DB" in stt_env()


def test_every_variable_the_model_reads_is_declared_in_the_overlay():
    """The general form of the two tests above, so the seventh instance fails
    here rather than in production."""
    read = set()
    for name in ("asr_engine.py", "session.py", "server.py", "openai_api.py", "audio_io.py"):
        if (FOLDER / name).is_file():
            read |= set(re.findall(r'os\.environ\.get\(\s*"([A-Z][A-Z0-9_]*)"', source(name)))
            read |= set(re.findall(r'os\.getenv\(\s*"([A-Z][A-Z0-9_]*)"', source(name)))

    declared = set(stt_env())
    # Set by the base compose for every slot, not this model's business.
    from_base = {"PORT", "PYTORCH_CUDA_ALLOC_CONF", "HUGGING_FACE_HUB_TOKEN",
                 "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "CUDA_VISIBLE_DEVICES",
                 "CUDA_MPS_PIPE_DIRECTORY", "CUDA_MPS_LOG_DIRECTORY", "LOG_LEVEL"}
    missing = read - declared - from_base
    assert not missing, (
        f"read by the model but declared nowhere, so its value is whatever the "
        f"code happens to default to: {sorted(missing)}"
    )


def test_the_dead_variable_is_not_quietly_carried_over():
    """ASR_DEFAULT_LANG is a knob that does nothing, and says otherwise.

    Upstream's docker-compose.yml sets it, and openai_api.py's module docstring
    says "an unnamed language defaults to ASR_DEFAULT_LANG rather than
    guessing". Line 40 then hardcodes `DEFAULT_LANGUAGE = "hi"` and nothing
    ever reads the variable. So the documentation, the compose file and the code
    disagree, and the two that an operator would check are the wrong ones.

    Not copied into our overlay: a knob that does nothing is worse than an
    absent one, because the first thing someone does when transcripts come back
    in the wrong language is set it.

    Matched against an actual read rather than a mention -- an earlier version
    of this test failed on upstream's docstring, which is exactly the text that
    makes the variable look live.
    """
    api = source("openai_api.py")
    assert 'DEFAULT_LANGUAGE = "hi"' in api, \
        "openai_api.py changed; ASR_DEFAULT_LANG may be live now -- re-check"
    reads = [line for line in api.split("\n")
             if "ASR_DEFAULT_LANG" in line
             and ("os.environ" in line or "os.getenv" in line)]
    assert not reads, f"it reads the variable now; declare it in the overlay: {reads}"
    assert "ASR_DEFAULT_LANG" not in stt_env(), (
        "ASR_DEFAULT_LANG is declared in the overlay but the model never reads "
        "it -- a knob that does nothing is worse than an absent one"
    )


# ------------------------------------------------------- reaching the model

def test_the_gateway_is_pointed_at_the_port_upstream_actually_binds():
    gw = overlay()["services"]["gateway"]["environment"]
    assert "8000" in str(gw["STT_UPSTREAM"]), (
        "upstream binds 8000, hardcoded. Without this the gateway talks to 8001 "
        "and every call 502s."
    )


def test_the_demo_path_is_configurable_rather_than_patched():
    gw = overlay()["services"]["gateway"]["environment"]
    assert gw["STT_DEMO_PATH"].endswith("/}") or gw["STT_DEMO_PATH"] == "/", \
        f"STT_DEMO_PATH is {gw['STT_DEMO_PATH']!r}; upstream serves its page at /"

    cfg = (ROOT / "gateway" / "app" / "config.py").read_text(encoding="utf-8")
    assert "_demo_path" in cfg, "the gateway cannot be told where a model's demo lives"
    assert "rstrip" not in cfg.split("def _demo_path")[1].split("\n\n\n")[0], (
        "_demo_path strips a trailing slash, which turns \"/\" into \"\" and "
        "silently falls back to /demo"
    )


def test_a_demo_path_of_just_a_slash_survives_being_read():
    """The specific bug the comment in _demo_path warns about. `_clean()` strips
    trailing slashes, so routing this through it would make the one value we
    actually need unrepresentable."""
    import os
    import sys
    sys.path.insert(0, str(ROOT / "gateway"))
    from app.config import _demo_path
    old = os.environ.get("STT_DEMO_PATH")
    try:
        os.environ["STT_DEMO_PATH"] = "/"
        assert _demo_path("stt") == "/"
        os.environ["STT_DEMO_PATH"] = ""
        assert _demo_path("stt") == "/demo", "an unset demo path must keep the convention"
        os.environ["STT_DEMO_PATH"] = "demo"
        assert _demo_path("stt") == "/demo", "a path without a leading slash must be normalised"
    finally:
        os.environ.pop("STT_DEMO_PATH", None)
        if old is not None:
            os.environ["STT_DEMO_PATH"] = old


# ------------------------------------------------------------- the catalogue

def catalogue() -> dict:
    doc = yaml.safe_load((ROOT / "models.yaml").read_text(encoding="utf-8"))
    return next(m for m in doc["stt"] if m["id"] == "indic-nemotron")


def test_the_catalogue_roster_matches_the_model():
    """models.yaml is what /models serves. A roster that disagrees with the
    model is a promise the slot cannot keep."""
    entry = catalogue()
    engine = source("asr_engine.py")
    block = engine.split("LANGUAGE_PROMPT_MAP = {")[1].split("}")[0]
    codes = set(re.findall(r'"([a-z]{2,4})":\s*"', block))
    codes.discard("bhili")                      # an alias for bhb, not a language
    assert set(entry["languages"]) == codes, (
        f"models.yaml lists {sorted(set(entry['languages']) ^ codes)} differently "
        f"from LANGUAGE_PROMPT_MAP"
    )


def test_the_catalogue_is_a_superset_of_the_models_it_can_replace():
    """The property that makes switching model safe. It held for
    indic-transcribe over indic-conformer, and it must hold here or a caller
    loses a language by a deploy-time choice it cannot see."""
    doc = yaml.safe_load((ROOT / "models.yaml").read_text(encoding="utf-8"))
    mine = set(catalogue()["languages"])
    for other in doc["stt"]:
        if other["id"] in ("indic-nemotron", "canary") or other["status"] != "ready":
            continue
        langs = other.get("languages") or []
        if not all(isinstance(x, str) and len(x) <= 4 for x in langs):
            continue                            # a prose placeholder, not a roster
        lost = set(langs) - mine
        assert not lost, f"switching from {other['id']} would lose {sorted(lost)}"


def test_the_declared_latency_matches_the_declared_geometry():
    entry = catalogue()
    raw = str(stt_env()["ASR_ATT_CONTEXT"])
    right = int(re.search(r"96,(\d+)", raw).group(1))
    # chunk = (right + 1) * subsampling(8) mel frames, at 10 ms per frame
    assert entry["latency_ms"] == (right + 1) * 8 * 10, (
        f"the catalogue says {entry['latency_ms']} ms but the overlay declares "
        f"96,{right}, which is {(right + 1) * 8 * 10} ms"
    )


def test_the_hardware_note_does_not_outlive_the_config_it_describes():
    """Successor to the "not yet run on hardware" guard, which did its job and
    came off the day this model served real audio.

    A record of what was observed is only worth having while it still describes
    what is deployed. The catalogue now says 320 ms was confirmed at /health;
    change the attention context and leave that sentence, and the catalogue is
    advertising a latency the deployment no longer produces -- which is the
    same failure as the original claim, one step later.

    `test_the_declared_latency_matches_the_declared_geometry` ties latency_ms to
    the overlay, so this closes the chain: observation -> catalogue -> overlay.
    """
    notes = catalogue()["notes"]
    assert "Not yet run on hardware" not in notes, (
        "it has run -- see the folder README. Drop the line rather than leaving "
        "the catalogue understating what is deployed."
    )
    confirmed = re.search(r"(\d+) ?ms confirmed", notes)
    assert confirmed, (
        "the catalogue no longer records what was confirmed on hardware; either "
        "restore it or drop this test with it"
    )
    assert int(confirmed.group(1)) == catalogue()["latency_ms"], (
        f"the catalogue records {confirmed.group(1)} ms confirmed on hardware but "
        f"declares latency_ms={catalogue()['latency_ms']}"
    )


# ----------------------------------------------------------------- fetch.sh

def test_the_fetcher_names_both_gated_checkpoints():
    body = source("fetch.sh")
    for repo in ("ai4bharat/indic-asr-nemotron-600m", "ai4bharat/bhili-asr-nemotron-600m"):
        assert repo in body, f"fetch.sh does not download {repo}"
    assert "gated" in body.lower(), \
        "fetch.sh does not say the repos are gated; a 401 does not explain itself"


def test_the_fetcher_checks_the_files_it_claims_to_have_downloaded():
    """A gated repo can return a directory of everything except the weights, and
    the CLI exits 0. Then the container fails on a model path, three steps
    later, and looks like a bad mount."""
    body = source("fetch.sh")
    for f in ("indic_nemotron_v1_1_sft_600k_lr1-averaged-40k.nemo",
              "indic_nemotron_bhili_sft_lr1-averaged.nemo"):
        assert f in body, f"fetch.sh never verifies {f} arrived"


def test_the_fetcher_parses():
    if not (FOLDER / "fetch.sh").is_file():
        pytest.skip("no fetcher")
    out = subprocess.run(["sh", "-n", str(FOLDER / "fetch.sh")],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


# ------------------------------------------- the demo actually reaches the page

def test_the_demo_page_is_fetched_from_where_the_model_serves_it():
    """End-to-end, against a stub shaped like the vendored server: a model that
    serves its page at `/` and has no `/demo` at all.

    The assertion that the gateway *has* a configurable demo path is not enough
    -- it can have one and not use it. Mutation testing proved that: reverting
    the fetch to a hardcoded "/demo" passed every other test in this file while
    breaking the only page a human ever looks at.
    """
    import sys

    from conftest import free_port, serve
    from fastapi import FastAPI

    sys.path.insert(0, str(ROOT / "gateway"))
    from app.config import Settings, Upstream
    from app.main import create_app
    from fastapi.testclient import TestClient

    def vendored_stub():
        a = FastAPI()
        a.get("/")(lambda: {"page": "nemotron-root"})
        a.get("/health")(lambda: {"status": "healthy"})
        return a                                  # note: no /demo, deliberately

    port = free_port()
    serve(vendored_stub(), port)
    cfg = Settings(
        Upstream("stt", f"http://127.0.0.1:{port}", "indic-nemotron", "/"),
        Upstream("tts", "", ""),
        Upstream("llm", "", ""),
    )
    with TestClient(create_app(cfg)) as c:
        r = c.get("/demo/stt")
        assert r.status_code == 200, (
            f"/demo/stt returned {r.status_code}. The gateway is fetching a path "
            f"this model does not serve -- most likely a hardcoded /demo."
        )
        assert r.json() == {"page": "nemotron-root"}


def test_a_model_that_serves_demo_conventionally_still_works():
    """The other half: adding the override must not break the three folders
    that do implement /demo."""
    import sys

    from conftest import free_port, serve
    from fastapi import FastAPI

    sys.path.insert(0, str(ROOT / "gateway"))
    from app.config import Settings, Upstream
    from app.main import create_app
    from fastapi.testclient import TestClient

    a = FastAPI()
    a.get("/demo")(lambda: {"page": "conventional"})
    port = free_port()
    serve(a, port)
    cfg = Settings(
        Upstream("stt", f"http://127.0.0.1:{port}", "indic-conformer"),
        Upstream("tts", "", ""),
        Upstream("llm", "", ""),
    )
    with TestClient(create_app(cfg)) as c:
        assert c.get("/demo/stt").json() == {"page": "conventional"}


# ------------------------------------------------------------- setup.sh path

def setup_source() -> str:
    from conftest import find_setup
    s = find_setup()
    if s is None:
        pytest.skip("setup.sh not in this checkout")
    # The repo may be checked out with CRLF on Windows; this is a shell script.
    return s.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_the_token_prompt_is_not_tts_only():
    """indic-nemotron's two checkpoints are gated, so an STT-only install has to
    be offered a token. It used to be asked for only when TTS was selected,
    because indic-parler's tokenizer was the only gated thing in the repo -- so
    picking nemotron alone would reach its fetch.sh with no credentials and
    abort the whole setup on something it was never asked for."""
    src = setup_source()
    prompt = [ln for ln in src.split("\n") if "HuggingFace token" in ln and "ask " in ln]
    assert prompt, "setup.sh no longer asks for a HuggingFace token at all"

    # The whole condition that guards the prompt, not a fixed number of lines
    # above it -- an earlier version of this test counted back six lines and
    # broke the moment the block grew a comment.
    head = src.split('ask "HuggingFace token')[0]
    guard = head[head.rindex("\nif "):]
    assert 'TTS_SEL" ] && [ -z "$HF_TOKEN' not in guard, (
        "the token prompt is gated on TTS again; an STT-only install with gated "
        "weights will never be asked"
    )
    assert "STT_SEL" in guard, f"the prompt does not consider the STT slot:\n{guard}"


def test_the_token_reaches_the_fetchers():
    """It reached the containers via .env but not the downloads, which run as
    child processes. A gated fetch then failed with the token sitting right
    there in the same script."""
    src = setup_source()
    assert re.search(r"^export HF_TOKEN", src, re.M), (
        "HF_TOKEN is not exported, so a model's fetch.sh cannot see it"
    )
    export_at = src.index("export HF_TOKEN")
    fetch_at = src.index('bash "$STT_DIR/fetch.sh"')
    assert export_at < fetch_at, "HF_TOKEN is exported after the fetchers run"


def test_a_previous_huggingface_login_is_not_ignored():
    """`huggingface-cli login` writes a token every fetcher and container can
    already read. Prompting anyway trains people to paste secrets they do not
    need to."""
    assert "hf_logged_in" in setup_source(), \
        "setup.sh prompts for a token even when the HF cache already holds one"


def test_the_per_folder_env_is_not_conformer_shaped_for_every_model():
    """It wrote INDIC_NEMO_PATH=.../IndicConformer.nemo into whichever STT
    folder was selected. Inert for a model that ignores dotenv -- nemotron does
    -- and a path to a nonexistent checkpoint for one that does not."""
    src = setup_source()
    conformer_keys = [ln for ln in src.split("\n") if "IndicConformer.nemo" in ln]
    assert conformer_keys, "the conformer path is gone entirely; check this is intended"
    guarded = 'if [ "$STT_SEL" = "indic-conformer" ]' in src
    assert guarded, (
        "the conformer-specific .env keys are written for every STT model; they "
        "belong behind a check on which model filled the slot"
    )


def test_setup_still_aborts_when_a_fetcher_fails(tmp_path):
    """`set -e` plus `[ -f x ] && bash x` means a failed download stops the
    install instead of building an image around missing weights. Verified as
    behaviour, not read off the source, because the interaction between set -e
    and AND-lists is exactly the kind of thing that gets 'tidied' later."""
    src = setup_source()
    assert re.search(r"^set -e\b", src, re.M), (
        "set -e is gone: a failed fetch.sh would now be followed by a build and "
        "a 'Stack started' on a container with no weights"
    )
    # tmp_path, not the repo: an earlier version of this wrote its probe file
    # into the repository root, where it showed up as an untracked file after
    # every run.
    script = tmp_path / "probe.sh"
    probe = subprocess.run(
        ["bash", "-c",
         'set -e\n'
         'printf "exit 1\\n" > "$0.f"\n'
         '[ -f "$0.f" ] && bash "$0.f"\n'
         'echo SURVIVED\n', str(script)],
        capture_output=True, text=True)
    assert "SURVIVED" not in probe.stdout, (
        "a failing fetch.sh no longer stops the script on this shell"
    )


# ------------------------------------------- switching away from this model

def test_this_is_the_only_overlay_that_configures_another_service():
    """Not a prohibition -- a flag.

    Every other model overlay touches only its own slot service. This one also
    sets gateway env, because upstream binds 8000 and serves its demo at `/`,
    and the alternative was editing files we do not own.

    The cost is that gateway config now depends on which model fills the STT
    slot, which is a coupling worth knowing about. If a second overlay starts
    doing this, the deploy instructions below need revisiting for it too.
    """
    crossing = {}
    for overlay_path in sorted(ROOT.glob("*/*/compose.extra.yml")):
        doc = yaml.safe_load(overlay_path.read_text(encoding="utf-8")) or {}
        slot = overlay_path.parent.parent.name
        others = set(doc.get("services") or {}) - {slot}
        # A model may bring sidecars of its own; those are its business.
        others = {s for s in others if s in ("gateway", "stt", "tts", "llm")}
        if others:
            crossing[overlay_path.parent.name] = sorted(others)
    assert crossing == {"indic-nemotron": ["gateway"]}, (
        f"the set of overlays reaching across services changed: {crossing}. "
        f"Each one needs its deploy instructions checked -- see "
        f"test_the_deploy_instructions_do_not_leave_the_gateway_stale."
    )


def test_the_deploy_instructions_do_not_leave_the_gateway_stale():
    """The failure this guards is silent and total.

    Because this model's overlay configures the gateway, `up -d --build stt`
    replaces the model container and leaves the gateway holding whatever it was
    given last. Switch from nemotron to indic-transcribe that way and the
    gateway still points at port 8000 and demo path `/`, while transcribe
    listens on 8001 and serves `/demo`: every request 502s and the demo 404s,
    with both containers reporting healthy.

    `up -d` with no service name recreates anything whose resolved config
    changed. So the folder's own docs must not tell anyone to do it the other
    way -- and the first draft of them did.
    """
    for name in ("README.md", "fetch.sh", ".env.example"):
        path = FOLDER / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for line in text.split("\n"):
            if "up -d" not in line:
                continue
            # Naming a service after `up -d` is what leaves the gateway behind.
            bad = re.search(r"up -d(?: --build)?\s+(stt|gateway)\b", line)
            if bad and "would leave" not in line and "only `stt`" not in line:
                raise AssertionError(
                    f"{name} tells the operator to bring up a single service:\n"
                    f"  {line.strip()}\n"
                    f"That leaves the gateway configured for the previous model."
                )


def test_setup_brings_up_the_whole_stack_not_one_slot():
    """setup.sh is the path most people will take, so it has to be the safe one."""
    src = setup_source()
    starts = [ln.strip() for ln in src.split("\n")
              if "up -d" in ln and "docker compose" in ln]
    assert starts, "setup.sh no longer starts the stack"
    full = [ln for ln in starts if re.search(r'up -d\s*$', ln)]
    assert full, (
        f"setup.sh starts named services only, which would leave the gateway "
        f"configured for whichever model was deployed before: {starts}"
    )


# --------------------------------------- the demo's assets, not just its HTML

def test_the_demo_pages_assets_are_reachable_through_the_gateway():
    """The check my first end-to-end test was missing.

    That one stubbed an upstream serving only `/`, proved `/demo/stt` returned
    the page, and stopped -- so it could not see that the page then asks for
    `/static/audio-processor.js` from the site root and gets a 404. The browser
    reports that as "Could not start the microphone. Unable to load a worklet's
    module", which reads like a permissions problem and sends you looking in
    entirely the wrong place.

    So this stub is shaped like the real server: page at `/`, worklet under
    `/static/`, and nothing at `/demo`.
    """
    import sys

    from conftest import free_port, serve
    from fastapi import FastAPI
    from fastapi.responses import PlainTextResponse

    sys.path.insert(0, str(ROOT / "gateway"))
    from app.config import Settings, Upstream
    from app.main import create_app
    from fastapi.testclient import TestClient

    a = FastAPI()
    a.get("/")(lambda: {"page": "nemotron-root"})
    a.get("/static/{path:path}", response_class=PlainTextResponse)(
        lambda path: f"asset:{path}")
    port = free_port()
    serve(a, port)

    cfg = Settings(
        Upstream("stt", f"http://127.0.0.1:{port}", "indic-nemotron", "/", ("/static",)),
        Upstream("tts", "", ""),
        Upstream("llm", "", ""),
    )
    with TestClient(create_app(cfg)) as c:
        assert c.get("/demo/stt").json() == {"page": "nemotron-root"}
        r = c.get("/static/audio-processor.js")
        assert r.status_code == 200, (
            f"/static/audio-processor.js returned {r.status_code}; the page loads "
            f"its AudioWorklet from an absolute path and the browser will report "
            f"this as a microphone failure"
        )
        assert r.text == "asset:audio-processor.js"
        # The query string the page appends for cache-busting must survive.
        assert c.get("/static/audio-processor.js?v=123").status_code == 200


def test_an_undeclared_asset_prefix_is_not_silently_routed():
    """The prefix is a declaration, not a guess. A slot that has not claimed
    `/static` must not receive requests for it -- otherwise adding any model
    with a `/static` page would start shadowing another slot's."""
    import sys

    from conftest import free_port, serve
    from fastapi import FastAPI

    sys.path.insert(0, str(ROOT / "gateway"))
    from app.config import Settings, Upstream
    from app.main import create_app
    from fastapi.testclient import TestClient

    a = FastAPI()
    a.get("/demo")(lambda: {"page": "conventional"})
    port = free_port()
    serve(a, port)
    cfg = Settings(Upstream("stt", f"http://127.0.0.1:{port}", "indic-conformer"),
                   Upstream("tts", "", ""), Upstream("llm", "", ""))
    with TestClient(create_app(cfg)) as c:
        assert c.get("/demo/stt").json() == {"page": "conventional"}
        assert c.get("/static/anything.js").status_code == 404


def test_two_slots_cannot_claim_the_same_root_prefix():
    """Whichever registered first would win silently, and the other slot's demo
    would load the wrong file rather than none -- a worse failure than a crash
    at startup, because it looks like the page working."""
    import sys
    sys.path.insert(0, str(ROOT / "gateway"))
    from app.config import Settings, Upstream
    from app.main import create_app

    cfg = Settings(
        Upstream("stt", "http://stt:8000", "indic-nemotron", "/", ("/static",)),
        Upstream("tts", "http://tts:8002", "orpheus", "/demo", ("/static",)),
        Upstream("llm", "", ""),
    )
    with pytest.raises(RuntimeError, match="only one slot can own a root path"):
        create_app(cfg)


def test_the_overlay_declares_the_prefix_the_page_actually_requests():
    """Read out of the vendored page, so the declaration cannot drift from it."""
    page = (FOLDER / "static" / "index.html").read_text(encoding="utf-8")
    requested = set(re.findall(r"""addModule\(['"](/[^/'"]+)/""", page))
    assert requested, "the page no longer loads a worklet from an absolute path"

    gw = yaml.safe_load((FOLDER / "compose.extra.yml").read_text(encoding="utf-8"))
    declared_raw = gw["services"]["gateway"]["environment"]["STT_DEMO_ASSETS"]
    declared = set(re.findall(r"/[a-z0-9_-]+", declared_raw.split(":-")[-1]))
    missing = requested - declared
    assert not missing, (
        f"the page loads assets from {sorted(missing)} but the overlay declares "
        f"{sorted(declared)}; those requests will 404 behind the gateway"
    )
