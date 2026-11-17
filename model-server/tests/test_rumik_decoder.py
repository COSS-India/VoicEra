"""The shared Mimi decoder and the per-stream bookkeeping in front of it.

tts/rumik-oss-1 used to decode each stream on its own and topped out at ~16
audio-seconds per second on the H200 whatever the load (decoder.py has the
numbers). The fix moves three things, and each can fail without an error:

  * FrameAssembler replaces re-running frames_from_tokens on the whole token
    list per chunk. If it disagrees with frames_from_tokens by one token, every
    later frame shifts and the stream is plausible-sounding noise.
  * FrameChunker hands each frame to the decoder exactly once. A slip there is
    a repeated or missing 80 ms of audio at every chunk boundary.
  * BatchedDecoder has to hand every stream back exactly its own audio, and
    must never put one decoder slot in a step twice. A mix-up is one caller
    hearing another caller's words.

None of this needs torch. The decoder itself (streaming.py) is checked against
MimiModel.decode in tests/test_rumik_streaming.py.
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


# -------------------------------------------------------------- FrameChunker

def drive(n_frames: int, chunk: int):
    chunker = codec.FrameChunker(codec.FrameAssembler(LAYOUT), chunk=chunk)
    out = [c for t in clean(n_frames) if (c := chunker.push(t)) is not None]
    if (tail := chunker.flush()) is not None:
        out.append(tail)
    return chunker, out


@pytest.mark.parametrize(("n_frames", "chunk"),
                         [(1, 2), (2, 2), (37, 2), (40, 4), (13, 3), (64, 1)])
def test_chunks_tile_the_stream_exactly_once(n_frames, chunk):
    chunker, out = drive(n_frames, chunk)
    assert [f for c in out for f in c] == chunker.assembler.frames
    assert chunker.emitted == n_frames


def test_every_chunk_but_the_last_is_full():
    _, out = drive(37, 4)
    assert [len(c) for c in out] == [4] * 9 + [1]


# ------------------------------------------------------------ BatchedDecoder

class Chunk:
    """Stands in for streaming.Chunk."""

    def __init__(self, slot, tag, start=False):
        self.slot, self.tag, self.start = slot, tag, start


class FakeStep:
    """Stands in for MimiStreamer.step: each chunk's 'audio' names the chunk.

    Holds the first call open until released, which is what lets requests that
    arrive meanwhile queue up behind it -- the shape a busy GPU produces.
    """

    def __init__(self, hold_first: bool = False):
        self.calls: list[list[int]] = []
        self.release = threading.Event()
        if not hold_first:
            self.release.set()

    def __call__(self, chunks):
        self.release.wait(5)
        slots = [c.slot for c in chunks]
        assert len(set(slots)) == len(slots), "a slot appeared twice in one step"
        self.calls.append(slots)
        return [f"{c.tag}".encode() for c in chunks]


async def test_every_stream_gets_its_own_audio_back():
    step = FakeStep()
    batched = decoder.BatchedDecoder(step, max_batch=64)
    batched.start()
    try:
        got = await asyncio.gather(*(batched.decode(Chunk(i, i)) for i in range(40)))
    finally:
        batched.stop()
    assert got == [f"{i}".encode() for i in range(40)]


async def test_requests_that_queue_behind_a_decode_are_decoded_together():
    step = FakeStep(hold_first=True)
    batched = decoder.BatchedDecoder(step, max_batch=64)
    batched.start()
    try:
        first = asyncio.ensure_future(batched.decode(Chunk(0, 0)))
        await asyncio.sleep(0.05)                        # the worker is now inside call 1
        rest = [asyncio.ensure_future(batched.decode(Chunk(i, i))) for i in range(1, 33)]
        await asyncio.sleep(0.05)
        step.release.set()
        await asyncio.gather(first, *rest)
    finally:
        batched.stop()
    # 33 streams, 2 calls: the one that was running, then everyone who queued.
    assert [len(c) for c in step.calls] == [1, 32]
    assert batched.snapshot()["decode_calls"] == 2


async def test_max_batch_caps_the_chunks_per_wakeup():
    step = FakeStep(hold_first=True)
    batched = decoder.BatchedDecoder(step, max_batch=8)
    batched.start()
    try:
        first = asyncio.ensure_future(batched.decode(Chunk(0, 0)))
        await asyncio.sleep(0.05)
        rest = [asyncio.ensure_future(batched.decode(Chunk(i, i))) for i in range(1, 21)]
        await asyncio.sleep(0.05)
        step.release.set()
        await asyncio.gather(first, *rest)
    finally:
        batched.stop()
    assert max(len(c) for c in step.calls) <= 8


def test_a_reused_slot_never_shares_a_step_and_keeps_its_order():
    # A cancelled stream left a chunk queued on slot 3; the stream that got slot 3
    # next queued its first chunk behind it.
    chunks = [Chunk(3, "old"), Chunk(5, "a"), Chunk(3, "new", start=True), Chunk(7, "b")]
    order = decoder.rounds(chunks)
    assert order == [[0, 1, 3], [2]]


async def test_a_failed_decode_reaches_its_callers_and_the_decoder_keeps_serving():
    calls = {"n": 0}

    def flaky(chunks):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("CUDA error")
        return [b"ok"] * len(chunks)

    batched = decoder.BatchedDecoder(flaky, max_batch=64)
    batched.start()
    try:
        with pytest.raises(RuntimeError, match="CUDA error"):
            await batched.decode(Chunk(1, 1))
        assert await batched.decode(Chunk(2, 2)) == b"ok"
    finally:
        batched.stop()


def test_warm_runs_each_width_with_a_fresh_start():
    step = FakeStep()
    batched = decoder.BatchedDecoder(step, max_batch=64)
    seen = []

    def make(slot, start):
        seen.append(start)
        return Chunk(slot, 0, start)

    batched.warm(make, [1, 4, 4, 128], steps=2)
    assert [len(c) for c in step.calls] == [1, 1, 4, 4]
    assert seen == [True, False] + [True] * 4 + [False] * 4
