"""One Mimi decoder for every stream: windows from all callers, decoded together.

Why this exists, measured on ace-h200 GPU 1 (H200, 0.12 of memory, shared
through MPS) with tests/bench/sweep.py, before it:

    closed loop  c=8 15.1 audio-s/s, c=16 14.1, c=32 16.0     (RTF p95 2.03)
    poisson      2 req/s passes, 4 req/s RTF p95 1.54
    burst        8 / 16 / 32 -> 16.7 / 15.9 / 16.2 audio-s/s

Output stopped at ~16 audio-seconds per second whatever the arrival pattern,
while vLLM itself was nowhere near busy (RTF 0.40 -> 0.44 from 1 to 8 streams).
Orpheus on the same card and the same 0.12 reaches 96 concurrent streams. The
difference was here: every stream called Mimi on its own, from a thread, once
per chunk. A Mimi decode of a few frames is dozens of small kernels -- its cost
is launch overhead, nearly independent of how many frames it decodes, which is
why cutting the window from 34 frames to 12 barely moved the ceiling and
halving the number of calls (2-frame chunks -> 4) doubled it.

So calls are what must not scale with streams, and they no longer do. This is
tts/orpheus's BatchedAudioDecoder, adapted: every stream puts its window on one
queue, a single worker takes whatever has queued, groups the windows by length
(only equal-length rows stack), and decodes each group in ONE call. N streams
cost one decode, not N. There is no timer: under load the GPU is busy long
enough for the next batch to fill by itself; when idle, a lone window goes
straight through.

The batching logic is written against a plain `decode_rows` callable so it can
be tested without torch; MimiRows is the real one.
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

#: A window is a list of frames, each frame the num_quantizers codes of one
#: 80 ms step. `new` is how many of its LAST frames to keep the audio of.
Window = Sequence[Sequence[int]]
DecodeRows = Callable[[list[Window], list[int]], list[bytes]]


class MimiRows:
    """Decode equal-length windows as one batch. Called only from the worker thread."""

    def __init__(self, mimi, samples_per_frame: int) -> None:
        self.mimi = mimi
        self.samples_per_frame = samples_per_frame

    def __call__(self, windows: list[Window], news: list[int]) -> list[bytes]:
        import torch

        frames = len(windows[0])
        if any(len(w) != frames for w in windows):
            raise ValueError("MimiRows decodes one window length per call")
        # [B, T, Q] -> [B, Q, T], the layout MimiModel.decode wants.
        codes = torch.tensor([[list(f) for f in w] for w in windows], dtype=torch.long)
        codes = codes.permute(0, 2, 1).contiguous().to(self.mimi.device)
        with torch.inference_mode():
            audio = self.mimi.decode(codes).audio_values[:, 0, :]          # [B, T*spf]
            # Scale and narrow on the GPU: half the bytes cross the bus, and it
            # is one conversion for the whole batch instead of one per stream.
            pcm = (audio.float().clamp(-1.0, 1.0) * 32767.0).to(torch.int16).cpu().numpy()
        spf = self.samples_per_frame
        return [pcm[i, pcm.shape[1] - new * spf:].astype("<i2").tobytes()
                for i, new in enumerate(news)]


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


class BatchedDecoder:
    """Coalesces decode requests from every concurrent stream into batched calls."""

    def __init__(self, decode_rows: DecodeRows, *, max_batch: int = 64) -> None:
        if max_batch < 1:
            raise ValueError("max_batch must be at least 1")
        self.decode_rows = decode_rows
        self.max_batch = max_batch
        self._queue: _queue.Queue = _queue.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        # Counters for GET /metrics. Plain ints written by the worker only.
        self.batches = 0
        self.rows = 0
        self.calls = 0
        self.decode_ms = _Recent()      # one sample per decode call (one length group)
        self.batch_rows = _Recent()     # rows per worker wake-up, all groups together
        self.wait_ms = _Recent()        # submit -> result, as a stream experiences it

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._thread = threading.Thread(target=self._worker, daemon=True, name="mimi-decode")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    # --------------------------------------------------------------- submit
    async def decode(self, window: Window, new: int) -> bytes:
        """The audio of the last `new` frames of `window`, as s16le PCM."""
        if self._loop is None:
            raise RuntimeError("BatchedDecoder.start() was not called")
        future = self._loop.create_future()
        self._queue.put((window, new, future, time.perf_counter()))
        return await future

    def warm(self, window_frames: int, quantizers: int, widths: Sequence[int]) -> None:
        """Run each batch width once, before traffic, so the first real burst
        does not pay for first-use allocations at a size never seen."""
        window = [[0] * quantizers for _ in range(window_frames)]
        for width in sorted({w for w in widths if 1 <= w <= self.max_batch}):
            started = time.perf_counter()
            self.decode_rows([window] * width, [1] * width)
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
        """Decode one wake-up's worth: each window length as its own call."""
        groups: dict[int, list[int]] = {}
        for i, (window, _, _, _) in enumerate(batch):
            groups.setdefault(len(window), []).append(i)
        results: list[bytes | BaseException] = [b""] * len(batch)
        for indexes in groups.values():
            started = time.perf_counter()
            try:
                out = self.decode_rows([batch[i][0] for i in indexes],
                                       [batch[i][1] for i in indexes])
            except Exception as exc:  # noqa: BLE001 -- every waiter in the group gets it
                log.exception("decode failed for a group of %d", len(indexes))
                out = [exc] * len(indexes)
            self.decode_ms.add((time.perf_counter() - started) * 1000.0)
            self.calls += 1
            for i, pcm in zip(indexes, out, strict=True):
                results[i] = pcm
        self.batches += 1
        self.rows += len(batch)
        self.batch_rows.add(float(len(batch)))
        now = time.perf_counter()
        for (_, _, future, submitted), result in zip(batch, results, strict=True):
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
