"""One Mimi decoder for every stream: chunks from all callers, decoded together.

Why this exists, measured on ace-h200 GPU 1 (H200, 0.12 of memory, shared
through MPS) with tests/bench/sweep.py, before it:

    closed loop  c=8 15.1 audio-s/s, c=16 14.1, c=32 16.0     (RTF p95 2.03)
    poisson      2 req/s passes, 4 req/s RTF p95 1.54
    burst        8 / 16 / 32 -> 16.7 / 15.9 / 16.2 audio-s/s

Output stopped at ~16 audio-seconds per second whatever the arrival pattern,
while vLLM itself was nowhere near busy. Every stream called Mimi on its own,
from a thread, once per chunk, and a small Mimi decode costs about the same
whatever its size -- so the number of calls is what must not scale with
streams. With this in front of the decoder the same card served 96 streams at
RTF p95 0.79 and 32 req/s of Poisson arrivals at 0.88.

This is tts/orpheus's BatchedAudioDecoder, adapted: every stream puts its next
chunk on one queue, a single worker takes whatever has queued, and the
streaming decoder (streaming.MimiStreamer) steps all of them in one batched
call. There is no timer: under load the GPU is busy long enough for the next
batch to fill by itself; when idle, a lone chunk goes straight through.

The batching logic is written against a plain `step` callable so it can be
tested without torch.
"""
from __future__ import annotations

import asyncio
import logging
import queue as _queue
import threading
import time
from collections import deque
from collections.abc import Callable, Sequence

log = logging.getLogger("rumik.decoder")

#: Takes a list of chunks (each naming its stream's slot) and returns one PCM
#: payload per chunk, in order. A slot appears at most once per call.
Step = Callable[[list], list[bytes]]


class _Recent:
    """Bounded samples for percentiles. Written by one thread, read by another."""

    def __init__(self, size: int = 2048) -> None:
        self._xs: deque[float] = deque(maxlen=size)

    def add(self, x: float) -> None:
        self._xs.append(x)

    def summary(self) -> dict:
        xs = sorted(self._xs)
        if not xs:
            return {"n": 0}

        def pct(q: float) -> float:
            return round(xs[min(len(xs) - 1, int(q * len(xs)))], 2)

        return {"n": len(xs), "p50": pct(0.50), "p95": pct(0.95), "max": round(xs[-1], 2)}


def rounds(chunks: Sequence) -> list[list[int]]:
    """Indexes split so no slot appears twice in one step, order kept per slot.

    Normally every chunk in a wake-up is from a different stream -- a stream
    awaits each chunk before sending the next. The exception is a stream that
    was cancelled with a chunk still queued: its slot can be handed to a new
    stream whose first chunk then queues behind the old one. That must not
    reach the decoder in the same step, and the old chunk must go first.
    """
    out: list[list[int]] = []
    level_of: dict[int, int] = {}
    for i, chunk in enumerate(chunks):
        level = level_of.get(chunk.slot, -1) + 1
        level_of[chunk.slot] = level
        if level == len(out):
            out.append([])
        out[level].append(i)
    return out


class BatchedDecoder:
    """Coalesces decode requests from every concurrent stream into batched steps."""

    def __init__(self, step: Step, *, max_batch: int = 64) -> None:
        if max_batch < 1:
            raise ValueError("max_batch must be at least 1")
        self.step = step
        self.max_batch = max_batch
        self._queue: _queue.Queue = _queue.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        # Counters for GET /metrics. Plain ints written by the worker only.
        self.batches = 0
        self.rows = 0
        self.calls = 0
        self.decode_ms = _Recent()      # one sample per step call
        self.batch_rows = _Recent()     # chunks per worker wake-up
        self.wait_ms = _Recent()        # submit -> result, as a stream experiences it

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="mimi-decode")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # --------------------------------------------------------------- submit
    async def decode(self, chunk) -> bytes:
        """The audio of `chunk`'s frames, as s16le PCM."""
        if self._loop is None:
            raise RuntimeError("BatchedDecoder.start() was not called")
        future = self._loop.create_future()
        self._queue.put((chunk, future, time.perf_counter()))
        return await future

    def warm(self, make_chunk: Callable[[int, bool], object], widths: Sequence[int],
             steps: int = 3) -> None:
        """Step each batch width a few times before traffic, so the first real
        burst does not pay for first-use allocations at a size never seen.
        `make_chunk(slot, start)` builds a throwaway chunk; every slot is reset
        by the first real chunk that uses it."""
        for width in sorted({w for w in widths if 1 <= w <= self.max_batch}):
            started = time.perf_counter()
            for i in range(steps):
                self.step([make_chunk(slot, i == 0) for slot in range(width)])
            log.info("decoder warmup: width %d in %.0f ms",
                     width, (time.perf_counter() - started) * 1000.0)

    # --------------------------------------------------------------- worker
    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                head = self._queue.get(timeout=0.5)
            except _queue.Empty:
                continue
            batch = [head]
            while len(batch) < self.max_batch:
                try:
                    batch.append(self._queue.get_nowait())
                except _queue.Empty:
                    break
            self._run(batch)

    def _run(self, batch: list[tuple]) -> None:
        chunks = [chunk for chunk, _, _ in batch]
        results: list[bytes | BaseException] = [b""] * len(batch)
        for indexes in rounds(chunks):
            started = time.perf_counter()
            try:
                out = self.step([chunks[i] for i in indexes])
            except Exception as exc:  # noqa: BLE001 -- every waiter in the step gets it
                log.exception("decode step failed for %d chunks", len(indexes))
                out = [exc] * len(indexes)
            self.decode_ms.add((time.perf_counter() - started) * 1000.0)
            self.calls += 1
            for i, pcm in zip(indexes, out, strict=True):
                results[i] = pcm
        self.batches += 1
        self.rows += len(batch)
        self.batch_rows.add(float(len(batch)))
        now = time.perf_counter()
        for (_, future, submitted), result in zip(batch, results, strict=True):
            self.wait_ms.add((now - submitted) * 1000.0)
            self._loop.call_soon_threadsafe(_settle, future, result)

    def snapshot(self) -> dict:
        return {
            "max_batch": self.max_batch,
            "wakeups": self.batches,
            "decode_calls": self.calls,
            "rows": self.rows,
            "rows_per_wakeup": self.batch_rows.summary(),
            "decode_call_ms": self.decode_ms.summary(),
            "stream_wait_ms": self.wait_ms.summary(),
            "queued": self._queue.qsize(),
        }


def _settle(future: asyncio.Future, result) -> None:
    if future.done():
        return
    if isinstance(result, BaseException):
        future.set_exception(result)
    else:
        future.set_result(result)
