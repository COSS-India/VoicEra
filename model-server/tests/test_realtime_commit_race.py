"""A commit arriving while an interim is in flight must still end the turn.

`_run_inference` opened with `if self._session.in_flight or ...: return`, and
`handle_commit` reached it via `_cancel_interim()` -- which only *schedules* a
CancelledError. So `in_flight` was still True when the final arrived and the
final returned immediately: no `...transcription.completed`, no
`input_audio_buffer.committed`, and no `reset_segment()`. Pipecat waits forever
for a transcript that never comes, and because the segment was never reset the
next utterance concatenates onto this one, so transcripts grow and repeat.

Nothing failed. Nothing logged. It presented as "the model is slow".

The existing realtime tests missed it because their stub returns instantly, so
no interim is ever outstanding when the commit lands. This one makes the model
slow on purpose, which puts every turn in the window. Measured against the
original code it dropped 30 of 30 turns; against the fix, none.
"""
import asyncio
import base64
import importlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest
import websockets

ROOT = Path(__file__).resolve().parent.parent
STT_DIR = ROOT / "stt" / "indic-conformer"

from conftest import free_port, serve  # noqa: E402

#: Enough turns that an intermittent regression shows up, few enough that the
#: 120 ms stub decode keeps this under ~6 s.
TURNS = 12


class SlowStub:
    """Decodes take 120 ms, so a 50 ms interim is always still running."""

    def transcribe(self, audio=None, batch_size=None, language_id=None):
        import time

        time.sleep(0.12)
        # One result per batch item. A stub returning a single result hands ""
        # to every request after the first whenever two share a batch, which
        # reads as the server losing a transcript.
        return [["नमस्ते दुनिया" for _ in audio]]

    def to(self, *a, **k):
        return self

    def freeze(self):
        return self


@pytest.fixture(scope="module")
def slow_ws_url():
    dummy = STT_DIR / "_race_stub.nemo"
    dummy.write_bytes(b"stub")
    os.environ["INDIC_NEMO_PATH"] = str(dummy)
    os.environ["BHILI_ENABLE"] = "no"
    os.environ["REALTIME_INTERIM_MS"] = "50"
    os.environ["REALTIME_MAX_SESSIONS"] = "8"

    sys.path.insert(0, str(STT_DIR))
    for mod in ("server", "realtime_ws"):
        sys.modules.pop(mod, None)

    server = importlib.import_module("server")
    server.main_model = SlowStub()
    server.bhili_model = None

    port = free_port()
    serve(server.app, port)
    server.main_model = SlowStub()
    server.bhili_model = None

    yield f"ws://127.0.0.1:{port}"
    dummy.unlink(missing_ok=True)


def _append(n_samples_24k: int = 9600) -> str:
    pcm = np.full(n_samples_24k, 1000, dtype=np.int16)
    return json.dumps({
        "type": "input_audio_buffer.append",
        "audio": base64.b64encode(pcm.tobytes()).decode("ascii"),
    })


def _session_update() -> str:
    return json.dumps({
        "type": "session.update",
        "session": {
            "type": "transcription",
            "audio": {"input": {"format": {"type": "audio/pcm", "rate": 24000}}},
        },
    })


@pytest.mark.asyncio
async def test_a_commit_racing_an_interim_still_ends_the_turn(slow_ws_url):
    dropped = []
    async with websockets.connect(f"{slow_ws_url}/v1/realtime?intent=transcription") as ws:
        await asyncio.wait_for(ws.recv(), 5.0)
        await ws.send(_session_update())
        await asyncio.wait_for(ws.recv(), 5.0)

        for turn in range(TURNS):
            await ws.send(_append())
            # Long enough for the interim to have started its decode, short
            # enough that it has not finished. This is the whole window.
            await asyncio.sleep(0.06)
            await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

            committed = False
            try:
                for _ in range(12):
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 3.0))
                    if msg["type"] == "input_audio_buffer.committed":
                        committed = True
                        break
            except TimeoutError:
                pass
            if not committed:
                dropped.append(turn)

    assert not dropped, (
        f"{len(dropped)}/{TURNS} turns produced no `input_audio_buffer.committed`; "
        f"the caller is left waiting on a transcript that never arrives. Turns: {dropped}"
    )
