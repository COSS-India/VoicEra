import contextlib
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

ROOT = Path(__file__).resolve().parent.parent
# Stubs stand in for the GPU stack; they must precede real packages.
sys.path.insert(0, str(Path(__file__).resolve().parent / "stubs"))
sys.path.insert(0, str(ROOT / "gateway"))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(app, port: int):
    """Run an ASGI app on a background thread and wait until it accepts.

    Shared by every test that needs a real socket rather than a test client:
    the gateway's whole job is streaming and cancellation, and ASGI test
    clients do not reproduce either.
    """
    cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(cfg)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        time.sleep(0.05)
        with contextlib.suppress(OSError), socket.create_connection(("127.0.0.1", port), 0.1):
            return server
    raise RuntimeError(f"server on {port} never came up")


def find_setup() -> Path | None:
    """Locate the model-server setup script, which has lived in three places.

    It sat at the repository root while model-server was one folder inside a
    larger tree; then inside model-server/ so the stack was self-contained; it
    now sits in scripts/ with every other runnable, as start-model-server.sh.
    Tests that pin its behaviour should not care which, and hardcoding one of
    them turns a move into silent skips -- which is what happened: the move to
    scripts/ landed while this function still named the old two paths, so it
    returned None and the nineteen tests that read the script stopped running
    while the suite went on reporting green.
    """
    root = Path(__file__).resolve().parent.parent
    candidates = (
        root.parent / "scripts" / "start-model-server.sh",
        root / "setup.sh",
        root.parent / "setup.sh",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


# --------------------------------------------------------------------------
# Say out loud what is not being checked.
#
# 44 tests in this suite reconcile the model catalogue against the voice
# pipeline that calls it: every model marked ready can be named by an agent,
# the audio formats the client decodes match what the models send, partial
# transcripts still reach the caller. They find the pipeline by path. When the
# path is wrong -- or, as now, when the client half is not in this repository at
# all -- they skip.
#
# A skip is invisible in a green summary line. That is the failure mode this
# hook exists for: the suite says "165 passed" while a quarter of what it
# claims to cover is not running.

CLIENT_MARKERS = ("voice_2_voice_server", "not present in this checkout")


def pytest_terminal_summary(terminalreporter, exitstatus, config):  # noqa: ARG001
    skipped = terminalreporter.stats.get("skipped", [])
    client = [r for r in skipped
              if any(m in str(getattr(r, "longrepr", "")) for m in CLIENT_MARKERS)]
    if not client:
        return

    w = terminalreporter
    w.write_sep("=", "NOT VERIFIED", red=True, bold=True)
    w.write_line(
        f"{len(client)} checks were skipped because the voice pipeline that calls "
        f"this server\nis not in this repository."
    )
    w.write_line("")
    w.write_line("Unverified while that is true:")
    w.write_line("  - every model marked `ready` can actually be named by an agent config")
    w.write_line("  - the client decodes the audio format each TTS model declares")
    w.write_line("  - partial transcripts still reach the caller mid-utterance")
    w.write_line("")
    w.write_line(
        "These are the checks that catch a model being deployable but unusable, "
        "which\nshows up first as a dropped call. Green above does not cover them."
    )
