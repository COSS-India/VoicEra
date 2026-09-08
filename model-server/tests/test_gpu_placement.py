"""Which GPU each slot lands on, and whether an operator can choose.

Two defects, found when an architect could not deploy onto a host with four
small cards.

**The default was ours.** Every service reserved `${GPU_DEVICE_IDS:-1}` and
`.env.example` shipped `GPU_DEVICE_IDS=1` uncommented, because 1 is our
allocation on ace-h200. On any other host that silently takes a card nobody
assigned, and on a single-GPU box it fails outright -- index 1 does not exist.
0 is the only index a machine with a GPU is guaranteed to have.

**One card for the whole stack.** `x-gpu` was a single YAML anchor merged into
stt, tts and llm, so all three shared one `device_ids`. STT on GPU 0, TTS on
GPU 1, LLM on GPU 2 was not expressible -- which is exactly the placement a host
with several small cards needs, and the reason the slot design exists.

Neither failed loudly. The first ran on the wrong card, the second ran three
models on one card until it ran out of memory. Both are the same shape as the
undeclared-geometry bug: a deployment value that only has one possible spelling,
and that spelling is the one our box wanted.

What this does NOT cover, and must not be read as covering: placing slots on
separate cards does not split a single model across cards. Both STT models are
single-GPU by construction. A model too large for one card is still too large.
"""
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "compose.model-server.yml"
MPS = ROOT / "compose.mps.yml"
SLOTS = ("stt", "tts", "llm")

#: The innermost `${VAR:-default}` that contains no further `${`.
INNERMOST = re.compile(r"\$\{([A-Z][A-Z0-9_]*)(?::-([^{}]*))?\}")


def resolve(expr: str, env: dict[str, str]) -> str:
    """Interpolate `${VAR:-default}`, nested, the way Compose does.

    A model of Compose, not Compose -- so `test_the_model_matches_real_compose`
    below runs the same cases through `docker compose config` wherever docker
    exists. Without that check this file would only be testing itself.
    """
    for _ in range(10):
        m = INNERMOST.search(expr)
        if not m:
            return expr
        value = env.get(m.group(1)) or (m.group(2) or "")
        expr = expr[: m.start()] + value + expr[m.end():]
    raise AssertionError(f"interpolation did not settle: {expr!r}")


def device_ids(service: str) -> str:
    doc = yaml.safe_load(BASE.read_text(encoding="utf-8"))
    devices = doc["services"][service]["deploy"]["resources"]["reservations"]["devices"]
    ids = devices[0]["device_ids"]
    assert len(ids) == 1, f"{service} reserves {ids}; expected one entry"
    return str(ids[0])


def mps_pipe(service: str) -> str:
    doc = yaml.safe_load(MPS.read_text(encoding="utf-8"))
    for vol in doc["services"][service]["volumes"]:
        if vol.endswith(":/tmp/nvidia-mps"):
            return vol.rsplit(":", 1)[0]
    raise AssertionError(f"{service} mounts no MPS pipe directory")


@pytest.mark.parametrize("slot", SLOTS)
def test_a_slot_with_nothing_configured_lands_on_gpu_zero(slot):
    """The only index guaranteed to exist. 1 was our card, not a default."""
    assert resolve(device_ids(slot), {}) == "0", (
        f"{slot} defaults to a card that is not guaranteed to exist. On a "
        f"single-GPU host this fails with a device that is not there; on a "
        f"multi-GPU host it quietly takes one nobody assigned."
    )


@pytest.mark.parametrize("slot", SLOTS)
def test_one_variable_still_moves_the_whole_stack(slot):
    """The common case stays one setting. Per-slot placement that forced three
    variables on a single-GPU host would be a worse default than the bug."""
    assert resolve(device_ids(slot), {"GPU_DEVICE_IDS": "1"}) == "1"


def test_the_slots_can_be_placed_on_different_cards():
    """The defect this file exists for: three models, three cards."""
    env = {"GPU_DEVICE_IDS": "0", "STT_GPU_DEVICE_IDS": "0",
           "TTS_GPU_DEVICE_IDS": "1", "LLM_GPU_DEVICE_IDS": "2"}
    placed = {slot: resolve(device_ids(slot), env) for slot in SLOTS}
    assert placed == {"stt": "0", "tts": "1", "llm": "2"}, (
        f"slots resolved to {placed}; they are still sharing one reservation"
    )


def test_each_slot_has_its_own_reservation_not_a_shared_anchor():
    """Resolution can look right while the anchor is still shared, if every
    slot happens to be set to the same card. Read the source instead."""
    text = BASE.read_text(encoding="utf-8")
    for slot in SLOTS:
        assert f"{slot.upper()}_GPU_DEVICE_IDS" in text, \
            f"nothing in the base compose names {slot.upper()}_GPU_DEVICE_IDS"
    assert "<<: *gpu\n" not in text, "the single shared GPU anchor is back"


@pytest.mark.parametrize("slot", SLOTS)
def test_the_mps_pipe_follows_the_slot_that_uses_it(slot):
    """A slot on GPU 2 must look for GPU 2's daemon.

    The pipe directory is per-GPU by convention. One path for all three slots
    would hand a slot on GPU 2 the daemon for GPU 0, and the failure is the
    client not finding a daemon -- nothing in the logs names the reason. That is
    the same defect that moved MPS out of the base file, one level down.
    """
    env = {"GPU_DEVICE_IDS": "0", f"{slot.upper()}_GPU_DEVICE_IDS": "2"}
    assert resolve(mps_pipe(slot), env) == "/tmp/nvidia-mps-gpu2"
    for other in SLOTS:
        if other != slot:
            assert resolve(mps_pipe(other), env) == "/tmp/nvidia-mps-gpu0", \
                f"placing {slot} moved {other}'s pipe directory"


@pytest.mark.parametrize("slot", SLOTS)
def test_an_explicit_pipe_path_still_wins(slot):
    """A host that puts the daemon somewhere other than the convention."""
    env = {"GPU_DEVICE_IDS": "1", "MPS_PIPE_DIR": "/var/run/mps"}
    assert resolve(mps_pipe(slot), env) == "/var/run/mps"


def test_the_mio_sidecar_follows_the_tts_slot():
    """It is part of the TTS slot. On a different card every token it generates
    would cross the PCIe bus to reach the model that asked for it."""
    overlay = ROOT / "tts" / "indic-mio" / "compose.extra.yml"
    if not overlay.is_file():
        pytest.skip("indic-mio not present in this checkout")
    doc = yaml.safe_load(overlay.read_text(encoding="utf-8"))
    for name, svc in doc.get("services", {}).items():
        devices = (svc.get("deploy", {}).get("resources", {})
                   .get("reservations", {}).get("devices"))
        if not devices:
            continue
        env = {"GPU_DEVICE_IDS": "0", "TTS_GPU_DEVICE_IDS": "3"}
        assert resolve(str(devices[0]["device_ids"][0]), env) == "3", (
            f"{name} does not follow TTS placement"
        )


def test_no_service_anywhere_still_defaults_to_our_card():
    """A straggler is invisible: it works on ace-h200 and only fails elsewhere."""
    stragglers = []
    # Shell scripts too. This globbed only YAML, which is how
    # compose-files.sh kept a `GPU_DEVICE_IDS:-1}` default that this very
    # test exists to forbid -- and it feeds MPS_PIPE_DIR, so the mismatch
    # it caused was the silent kind.
    for f in (sorted(ROOT.glob("compose*.yml")) + sorted(ROOT.glob("*/*/compose*.yml"))
              + sorted(ROOT.glob("*.sh")) + sorted(ROOT.glob("*/*/*.sh"))):
        for n, line in enumerate(f.read_text(encoding="utf-8").split("\n"), 1):
            if "GPU_DEVICE_IDS:-1}" in line:
                stragglers.append(f"{f.relative_to(ROOT).as_posix()}:{n}")
    assert not stragglers, f"still defaulting to GPU 1: {stragglers}"


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available here")
def test_the_model_matches_real_compose():
    """Everything above resolves interpolation with a regex. This runs the same
    files through Compose itself, so the model cannot drift away from the tool
    the deployment actually uses."""
    env = {"GPU_DEVICE_IDS": "0", "STT_GPU_DEVICE_IDS": "0",
           "TTS_GPU_DEVICE_IDS": "1", "LLM_GPU_DEVICE_IDS": "2"}
    out = subprocess.run(
        ["docker", "compose", "-f", str(BASE), "--project-directory", str(ROOT), "config"],
        capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", **env},
    )
    if out.returncode != 0:
        pytest.skip(f"compose config unavailable: {out.stderr.strip()[:200]}")
    doc = yaml.safe_load(out.stdout)
    for slot, want in (("stt", "0"), ("tts", "1"), ("llm", "2")):
        svc = doc["services"].get(slot)
        if svc is None:
            continue
        got = str(svc["deploy"]["resources"]["reservations"]["devices"][0]["device_ids"][0])
        assert got == want, f"compose put {slot} on {got}, the model said {want}"
