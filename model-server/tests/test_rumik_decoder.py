"""The shared Mimi decoder and the per-stream bookkeeping in front of it.

tts/rumik-oss-1 used to decode each stream on its own and topped out at ~16
audio-seconds per second on the H200 whatever the load (decoder.py has the
numbers). The fix moves three things, and each can fail without an error:

  * FrameAssembler replaces re-running frames_from_tokens on the whole token
    list per chunk. If it disagrees with frames_from_tokens by one token, every
    later frame shifts and the stream is plausible-sounding noise.
  * StreamWindows decides what to decode and what to keep. A slip there is a
    repeated or missing 80 ms of audio at every chunk boundary.
  * BatchedDecoder has to hand every stream back exactly its own row. A mix-up
    is one caller hearing another caller's words.

None of this needs torch; MimiRows, the only torch code, is exercised on
hardware by the load bench.
"""
import asyncio
import importlib.util
import random
import sys
import threading
from pathlib import Path

import pytest

MODEL = Path(__file__).resolve().parent.parent / "tts" / "rumik-oss-1"


def _load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, MODEL / file)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module          # before exec: @dataclass resolves through it
    spec.loader.exec_module(module)
    return module


codec = _load("rumik_codec_for_decoder", "codec.py")
decoder = _load("rumik_decoder", "decoder.py")

LAYOUT = codec.CodecLayout(
    first_unit_id=261008, last_unit_id=277391, num_quantizers=8, codebook_size=2048,
    audio_end_token_id=277394, frame_rate_hz=12.5, speakers=("Ira",),
)
Q = LAYOUT.num_quantizers


def unit(code: int, q: int) -> int:
    return codec.unit_token(code, q, LAYOUT)


def clean(n_frames: int, seed: int = 0) -> list[int]:
    rng = random.Random(seed)
    return [unit(rng.randrange(2048), q) for _ in range(n_frames) for q in range(Q)]


def noisy(n: int, seed: int) -> list[int]:
    """Mostly well-formed audio with every way a frame can be abandoned mixed in."""
    rng = random.Random(seed)
    out, q = [], 0
    for _ in range(n):
        roll = rng.random()
        if roll < 0.04:
            out.append(rng.randrange(0, 1000))              # stray text id
        elif roll < 0.08:
            out.append(unit(rng.randrange(2048), rng.randrange(Q)))   # off the round robin
        elif roll < 0.09:
            out.append(unit(rng.randrange(2048), 0))        # an early quantizer-0
            q = 1
            continue
        else:
            out.append(unit(rng.randrange(2048), q))
        q = (q + 1) % Q
    if rng.random() < 0.5:
        out.append(LAYOUT.audio_end_token_id)
        out.extend(clean(3, seed + 1))                      # ignored: after </audio>
    return out


# ------------------------------------------------------------ FrameAssembler

@pytest.mark.parametrize("seed", range(40))
def test_the_assembler_agrees_with_frames_from_tokens_token_by_token(seed):
    tokens = noisy(400, seed)
    assembler = codec.FrameAssembler(LAYOUT)
    completed = sum(assembler.push(t) for t in tokens)
    expected = codec.frames_from_tokens(tokens, LAYOUT)
    assert assembler.frames == expected
    assert completed == len(expected)


def test_the_assembler_stops_at_the_end_token():
    assembler = codec.FrameAssembler(LAYOUT)
    for t in clean(2) + [LAYOUT.audio_end_token_id] + clean(2, 9):
        assembler.push(t)
    assert len(assembler.frames) == 2 and assembler.ended


# ------------------------------------------------------------- StreamWindows

def drive(n_frames: int, chunk: int, context: int):
    windows = codec.StreamWindows(codec.FrameAssembler(LAYOUT), chunk=chunk, context=context)
    out = [w for t in clean(n_frames) if (w := windows.push(t)) is not None]
    if (tail := windows.flush()) is not None:
        out.append(tail)
    return windows, out


@pytest.mark.parametrize(("n_frames", "chunk", "context"),
                         [(1, 2, 32), (2, 2, 32), (37, 2, 32), (40, 4, 8), (13, 3, 0), (64, 1, 5)])
def test_kept_frames_tile_the_stream_exactly_once(n_frames, chunk, context):
    windows, out = drive(n_frames, chunk, context)
    kept = [f for window, new in out for f in window[len(window) - new:]]
    assert kept == windows.assembler.frames          # no gap, no repeat, in order
    assert windows.emitted == n_frames


@pytest.mark.parametrize(("chunk", "context"), [(2, 32), (4, 8)])
def test_every_window_carries_as_much_left_context_as_exists(chunk, context):
    _, out = drive(60, chunk, context)
    emitted = 0
    for window, new in out:
        assert len(window) - new == min(context, emitted)
        emitted += new


def test_steady_state_windows_share_one_length_so_they_batch():
    _, out = drive(100, 2, 32)
    lengths = [len(w) for w, _ in out]
    assert set(lengths[16:-1]) == {34}


# ------------------------------------------------------------ BatchedDecoder

class FakeRows:
    """Stands in for MimiRows: each row's 'audio' names the row, so a mix-up shows.

    Holds the first call open until released, which is what lets requests that
    arrive meanwhile queue up behind it -- the shape a busy GPU produces.
    """

    def __init__(self, hold_first: bool = False):
        self.calls: list[list[int]] = []
        self.release = threading.Event()
        if not hold_first:
            self.release.set()

    def __call__(self, windows, news):
        self.release.wait(5)
        self.calls.append([len(w) for w in windows])
        return [f"{w[-1][0]}:{new}".encode() for w, new in zip(windows, news, strict=True)]


def window(tag: int, frames: int = 34):
    return [[tag] * Q for _ in range(frames)]


async def test_every_stream_gets_its_own_row_back():
    rows = FakeRows()
    batched = decoder.BatchedDecoder(rows, max_batch=64)
    batched.start()
    try:
        got = await asyncio.gather(*(batched.decode(window(i), 2) for i in range(40)))
    finally:
        batched.stop()
    assert got == [f"{i}:2".encode() for i in range(40)]


async def test_requests_that_queue_behind_a_decode_are_decoded_together():
    rows = FakeRows(hold_first=True)
    batched = decoder.BatchedDecoder(rows, max_batch=64)
    batched.start()
    try:
        first = asyncio.ensure_future(batched.decode(window(0), 2))
        await asyncio.sleep(0.05)                        # the worker is now inside call 1
        rest = [asyncio.ensure_future(batched.decode(window(i), 2)) for i in range(1, 33)]
        await asyncio.sleep(0.05)
        rows.release.set()
        await asyncio.gather(first, *rest)
    finally:
        batched.stop()
    # 33 streams, 2 calls: the one that was running, then everyone who queued.
    assert [len(c) for c in rows.calls] == [1, 32]
    assert batched.snapshot()["decode_calls"] == 2


async def test_unequal_windows_are_decoded_as_separate_groups():
    rows = FakeRows(hold_first=True)
    batched = decoder.BatchedDecoder(rows, max_batch=64)
    batched.start()
    try:
        first = asyncio.ensure_future(batched.decode(window(0), 2))
        await asyncio.sleep(0.05)
        rest = [asyncio.ensure_future(batched.decode(window(i, 34 if i % 2 else 4), 2))
                for i in range(1, 9)]
        await asyncio.sleep(0.05)
        rows.release.set()
        got = await asyncio.gather(first, *rest)
    finally:
        batched.stop()
    assert sorted(len(c) for c in rows.calls[1:]) == [4, 4]
    assert all(set(c) == {c[0]} for c in rows.calls)     # one length per call
    assert got == [f"{i}:2".encode() for i in range(9)]


async def test_max_batch_caps_the_rows_per_call():
    rows = FakeRows(hold_first=True)
    batched = decoder.BatchedDecoder(rows, max_batch=8)
    batched.start()
    try:
        first = asyncio.ensure_future(batched.decode(window(0), 2))
        await asyncio.sleep(0.05)
        rest = [asyncio.ensure_future(batched.decode(window(i), 2)) for i in range(1, 21)]
        await asyncio.sleep(0.05)
        rows.release.set()
        await asyncio.gather(first, *rest)
    finally:
        batched.stop()
    assert max(len(c) for c in rows.calls) <= 8


async def test_a_failed_decode_reaches_its_callers_and_the_decoder_keeps_serving():
    calls = {"n": 0}

    def flaky(windows, news):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("CUDA error")
        return [b"ok"] * len(windows)

    batched = decoder.BatchedDecoder(flaky, max_batch=64)
    batched.start()
    try:
        with pytest.raises(RuntimeError, match="CUDA error"):
            await batched.decode(window(1), 2)
        assert await batched.decode(window(2), 2) == b"ok"
    finally:
        batched.stop()


def test_warm_runs_each_width_once():
    rows = FakeRows()
    batched = decoder.BatchedDecoder(rows, max_batch=64)
    batched.warm(34, Q, [1, 2, 4, 8, 16, 32, 64, 64, 128])
    assert [len(c) for c in rows.calls] == [1, 2, 4, 8, 16, 32, 64]
