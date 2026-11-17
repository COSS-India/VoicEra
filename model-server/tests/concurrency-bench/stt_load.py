#!/usr/bin/env python3
"""Concurrency test for streaming STT (indic-nemotron's WebSocket protocol).

Each request is one live call: open the socket, stream one clip at real time in
160 ms frames, send flush_eos, wait for the final transcript. N such calls are
started per round, either

  Test A  (--mode sync)    all N at the same instant, or
  Test B  (--mode random)  at N random times within --arrival-window seconds
                           (Poisson arrivals conditioned on exactly N; a fresh
                           draw every round).

Each N runs --rounds rounds and the rounds are pooled. Warm-up traffic runs
first and is discarded. Nothing stops early.

    python stt_load.py --url http://HOST:8100 --manifest corpus/manifest.json \\
        --language mr --out-dir results/my-run

RTF (real-time factor) = time the server spent on the utterance / audio length.
The server reports `latency_ms` on every partial (batch-queue wait plus model
step) and on the final (the flush); RTF is their sum divided by the audio
duration. Below 1 the server keeps up with live speech. A server that does not
send `latency_ms` gets RTF "NOT MEASURED" rather than a made-up number.

Each round opens its N sockets together, then starts each utterance's speech
at its scheduled time. Timing is open-loop: every schedule is fixed before the
round starts and every latency is measured from the SCHEDULED time, so a slow
connect or a stalled socket shows up as latency instead of silently moving the
clock.

Protocol: connect to <ws-path>?language=xx, read {"status":"ready"}, send
{"action":"hello","sampleRate":16000}, stream binary int16 frames, send
{"action":"flush_eos"}, read {"is_final":true,"text":...}.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import random
import re
import sys
import time
import unicodedata
import wave
from pathlib import Path

import httpx
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (  # noqa: E402
    LoopLag,
    RequestLog,
    batch_starts,
    parse_levels,
    run_meta,
    say,
    sleep_until,
    stats,
    warm_up,
    warn,
    write_json,
)
from gpu_sampler import GpuSampler  # noqa: E402

RATE = 16000
CHUNK_S = 0.16
CHUNK_BYTES = int(RATE * CHUNK_S) * 2          # 5120 bytes = the server's wire frame
FINAL_TIMEOUT_S = 30.0


# --------------------------------------------------------------------------- corpus
def load_corpus(manifest: Path) -> list[dict]:
    m = json.loads(manifest.read_text())
    clips = []
    for c in m["clips"]:
        path = Path(c["path"])
        if not path.is_absolute():
            path = manifest.parent / path
        with wave.open(str(path), "rb") as w:
            if (w.getframerate(), w.getsampwidth(), w.getnchannels()) != (RATE, 2, 1):
                raise SystemExit(f"{path}: must be 16 kHz mono int16 (use make_corpus.py import)")
            pcm = w.readframes(w.getnframes())
        pcm += bytes((-len(pcm)) % CHUNK_BYTES)
        c = dict(c)
        c["chunks"] = [pcm[i:i + CHUNK_BYTES] for i in range(0, len(pcm), CHUNK_BYTES)]
        c["speech_s"] = len(c["chunks"]) * CHUNK_S
        clips.append(c)
    return clips


# --------------------------------------------------------------------------- accuracy
_PUNCT = re.compile(r"[।॥.,!?;:\"'()\[\]{}\-–—…]")


def norm(t: str) -> str:
    t = unicodedata.normalize("NFC", t or "")
    return " ".join(_PUNCT.sub(" ", t).split())


def lev(a: list | str, b: list | str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(ref: str, hyp: str) -> float:
    r, h = norm(ref).replace(" ", ""), norm(hyp).replace(" ", "")
    return lev(r, h) / max(1, len(r))


def wer(ref: str, hyp: str) -> float:
    r, h = norm(ref).split(), norm(hyp).split()
    return lev(r, h) / max(1, len(r))


# --------------------------------------------------------------------------- one call
class Utt:
    """One utterance on one socket, and everything measured about it."""

    def __init__(self, clip: dict, t_speech: float):
        self.clip, self.t_speech = clip, t_speech
        self.t_end = t_speech + clip["speech_s"]
        self.partials = 0
        self.first_partial: float | None = None
        self.final: str | None = None
        self.t_final: float | None = None
        self.step_ms: list[float] = []
        self.flush_ms: float | None = None
        self.lateness: list[float] = []
        self.connect_ms: float | None = None
        self.error: str | None = None
        self.done = asyncio.Event()

    def row(self) -> dict:
        ok = self.error is None and self.final is not None
        measured = bool(self.step_ms) or self.flush_ms is not None
        server_ms = sum(self.step_ms) + (self.flush_ms or 0.0)
        r = {"clip": self.clip["id"], "bucket": self.clip["bucket"],
             "speech_s": round(self.clip["speech_s"], 3), "ok": ok, "error": self.error,
             "connect_ms": round(self.connect_ms, 1) if self.connect_ms is not None else None,
             "partials": self.partials,
             "final_ms": round((self.t_final - self.t_end) * 1000, 1) if ok else None,
             "first_partial_ms": round((self.first_partial - self.t_speech) * 1000, 1)
             if self.first_partial else None,
             "send_late_ms_max": round(max(self.lateness) * 1000, 1) if self.lateness else None,
             "server_ms": round(server_ms, 1) if measured else None,
             "rtf": round(server_ms / (self.clip["speech_s"] * 1000), 4)
             if ok and measured else None,
             "text": self.final}
        if ok:
            r["cer"] = round(cer(self.clip["text"], self.final), 4)
            r["wer"] = round(wer(self.clip["text"], self.final), 4)
        return r


async def one_call(ws_url: str, clip: dict, t_speech: float) -> Utt:
    """Connect, stream one clip on its fixed schedule, flush, read the final.

    If the connect runs past the scheduled start, the frame schedule does NOT
    move: overdue frames go out at once and the delay lands in final_ms.
    """
    u = Utt(clip, t_speech)
    ws = None
    reader = None
    try:
        t = time.monotonic()
        ws = await websockets.connect(ws_url, max_size=None, open_timeout=30,
                                      ping_interval=None, close_timeout=5)
        ready = json.loads(await asyncio.wait_for(ws.recv(), 30))
        if ready.get("status") != "ready":
            raise RuntimeError(f"not ready: {ready}")
        await ws.send(json.dumps({"action": "hello", "sampleRate": RATE}))
        u.connect_ms = (time.monotonic() - t) * 1000

        async def read() -> None:
            try:
                async for msg in ws:
                    if isinstance(msg, bytes | bytearray):
                        continue
                    ev = json.loads(msg)
                    if "error" in ev:
                        u.error = f"server: {ev['error']}"[:160]
                        u.done.set()
                        return
                    if "is_final" not in ev:
                        continue                                  # status frames
                    now = time.monotonic()
                    if ev["is_final"]:
                        if ev.get("endpoint") == "silence":
                            continue                              # a VAD final, not our flush
                        u.final, u.t_final = ev.get("text") or "", now
                        if ev.get("latency_ms") is not None:
                            u.flush_ms = float(ev["latency_ms"])
                        u.done.set()
                        return
                    if ev.get("latency_ms") is not None:
                        u.step_ms.append(float(ev["latency_ms"]))
                    if ev.get("text"):
                        u.partials += 1
                        if u.first_partial is None:
                            u.first_partial = now
            except Exception as e:                               # noqa: BLE001
                u.error = u.error or f"socket: {type(e).__name__}: {e}"[:160]
            finally:
                u.done.set()

        reader = asyncio.ensure_future(read())
        for k, ch in enumerate(clip["chunks"]):
            target = t_speech + (k + 1) * CHUNK_S
            await sleep_until(target)
            u.lateness.append(max(0.0, time.monotonic() - target))
            await ws.send(ch)
        await ws.send(json.dumps({"action": "flush_eos"}))
        await asyncio.wait_for(u.done.wait(), FINAL_TIMEOUT_S + clip["speech_s"])
        if u.final is None and u.error is None:
            u.error = "socket closed before the final"
    except (asyncio.TimeoutError, TimeoutError):  # noqa: UP041 -- distinct on Python 3.10
        u.error = u.error or "timeout"
    except Exception as e:                                       # noqa: BLE001
        u.error = u.error or f"{type(e).__name__}: {e}"[:160]
    finally:
        if reader:
            reader.cancel()
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()
    return u


# --------------------------------------------------------------------------- server state
async def health(client: httpx.AsyncClient, url: str) -> dict:
    try:
        return (await client.get(url, timeout=10)).json()
    except Exception:                                            # noqa: BLE001
        return {}


async def wait_idle(client: httpx.AsyncClient, url: str, timeout: float = 90) -> bool:
    """Wait until the server reports no active streams (skipped if it cannot say)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        h = await health(client, url)
        if not h:
            return False
        if not h.get("active_streams"):
            return True
        await asyncio.sleep(0.5)
    return False


# --------------------------------------------------------------------------- one cell
async def run_cell(a: argparse.Namespace, pool: list[dict], mode: str, n: int,
                   log: RequestLog) -> dict:
    rng = random.Random(a.seed + n)
    rows: list[dict] = []
    async with httpx.AsyncClient() as client:
        await wait_idle(client, a.health_url)
        before = await health(client, a.health_url)
        t_cell = time.monotonic()
        with GpuSampler(a.gpu_index) as gpu, LoopLag() as lag:
            for rnd in range(a.rounds):
                t0 = time.monotonic() + 0.5
                starts = batch_starts(n, mode, t0, a.arrival_window, rng)
                plan = [(t, rng.choice(pool)) for t in starts]
                utts = await asyncio.gather(*(one_call(a.ws_url, c, t) for t, c in plan))
                for (t, _), u in zip(plan, utts, strict=True):
                    rows.append({"test": mode, "n": n, "round": rnd + 1,
                                 "start_offset_ms": round((t - t0) * 1000, 1), **u.row()})
                await wait_idle(client, a.health_url)
                await asyncio.sleep(1.0)                          # drain between rounds
        wall = time.monotonic() - t_cell
        after = await health(client, a.health_url)
    await asyncio.sleep(a.cooldown)
    log.write(rows)

    ok = [r for r in rows if r["ok"]]
    b0, b1 = before.get("batching") or {}, after.get("batching") or {}
    dbatch = b1.get("batches", 0) - b0.get("batches", 0)
    ditems = b1.get("items", 0) - b0.get("items", 0)
    rtf_missing = bool(ok) and all(r["rtf"] is None for r in ok)
    return {
        "n": n, "mode": mode, "rounds": a.rounds,
        "arrival_window_s": a.arrival_window if mode == "random" else 0.0,
        "requests": len(rows), "ok": len(ok), "failed": len(rows) - len(ok),
        "errors": sorted({r["error"] for r in rows if r["error"]})[:8],
        "rtf": {"n": 0, "note": "NOT MEASURED (server sent no latency_ms)"} if rtf_missing
        else stats([r["rtf"] for r in ok]),
        "final_ms": stats([r["final_ms"] for r in ok]),
        "first_partial_ms": stats([r["first_partial_ms"] for r in ok]),
        "connect_ms": stats([r["connect_ms"] for r in rows]),
        "send_late_ms": stats([r["send_late_ms_max"] for r in rows]),
        "cer_pct": stats([r["cer"] * 100 for r in ok]),
        "wer_pct": stats([r["wer"] * 100 for r in ok]),
        "speech_seconds_per_s": round(sum(r["speech_s"] for r in ok) / wall, 2) if wall else None,
        "server_batching": {"batches": dbatch, "items": ditems,
                            "mean_batch": round(ditems / dbatch, 2) if dbatch > 0 else None,
                            "max_batch": b1.get("max_batch")} if b1 else "NOT REPORTED",
        "loop_lag_ms": lag.summary(),
        "client_bound_suspected": lag.summary()["client_bound_suspected"],
        "gpu": gpu.summary(),
        "wall_s": round(wall, 1),
    }


def line(c: dict) -> str:
    r, f = c["rtf"], c["final_ms"]
    return (f"ok={c['ok']}/{c['requests']}  RTF p50={r.get('p50')} p95={r.get('p95')} "
            f"p99={r.get('p99')} max={r.get('max')}  final p95={f.get('p95')} ms  "
            f"CER={round(c['cer_pct'].get('mean') or 0, 1)}%"
            + ("  CLIENT-BOUND" if c["client_bound_suspected"] else ""))


# --------------------------------------------------------------------------- main
async def main_async(a: argparse.Namespace) -> int:
    clips = load_corpus(Path(a.manifest))
    pool = [c for c in clips if a.bucket in ("all", c["bucket"])]
    if not pool:
        raise SystemExit(f"no clips in bucket {a.bucket!r}")
    out = Path(a.out_dir) / "stt"
    out.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient() as client:
        h = await health(client, a.health_url)
    if not h:
        warn(f"no JSON from {a.health_url}; idle checks and batching counters are off")
    say(f"STT  {a.ws_url}\n     {len(pool)} '{a.bucket}' clips of {len(clips)}; "
        f"levels {a.levels}; {a.rounds} rounds; tests {a.mode}")
    write_json(out / "run_meta.json", run_meta(a, h, {"clips_in_pool": len(pool)}))

    if a.warmup_singles or a.warmup_batches:
        say("\nwarm-up (discarded)")
        wrng = random.Random(a.seed - 1)

        async def single() -> None:
            await one_call(a.ws_url, wrng.choice(pool), time.monotonic() + 0.1)

        async def batch(b: int) -> None:
            t0 = time.monotonic() + 0.5
            await asyncio.gather(*(one_call(a.ws_url, wrng.choice(pool), t0) for _ in range(b)))

        wlog = await warm_up(single, batch, a.warmup_singles,
                             parse_levels(a.warmup_batches), a.warmup_budget)
        write_json(out / "warmup.json", wlog)
        await asyncio.sleep(a.cooldown)

    for mode in (["sync", "random"] if a.mode == "both" else [a.mode]):
        title = "Test A - single batch" if mode == "sync" else \
            f"Test B - random arrivals within {a.arrival_window:g} s"
        say(f"\n{title}")
        log = RequestLog(out / f"requests_{mode}.jsonl")
        cells = []
        for n in parse_levels(a.levels):
            cell = await run_cell(a, pool, mode, n, log)
            cells.append(cell)
            say(f"  N={n:<4} {line(cell)}")
            write_json(out / f"batch_{mode}.json",
                       {"model": "stt", "test": mode, "language": a.language,
                        "endpoint": a.ws_url, "bucket": a.bucket, "cells": cells})
    async with httpx.AsyncClient() as client:
        meta = json.loads((out / "run_meta.json").read_text())
        meta["health_at_end"] = await health(client, a.health_url)
        write_json(out / "run_meta.json", meta)
    say(f"\nwrote {out}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8100",
                    help="server base URL: the gateway, or the STT container directly")
    ap.add_argument("--ws-path", default="/v1/asr/ws")
    ap.add_argument("--health-path", default="/stt/health",
                    help="/stt/health through the gateway, /health on the container directly")
    ap.add_argument("--language", default="mr")
    ap.add_argument("--manifest", required=True, help="corpus manifest from make_corpus.py")
    ap.add_argument("--bucket", default="medium", choices=["short", "medium", "long", "all"])
    ap.add_argument("--mode", default="both", choices=["sync", "random", "both"],
                    help="sync = Test A, random = Test B")
    ap.add_argument("--levels", default="1,2,4,8,16,32,64,128,256")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--arrival-window", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--warmup-singles", type=int, default=5)
    ap.add_argument("--warmup-batches", default="8,64,256", help="empty string for none")
    ap.add_argument("--warmup-budget", type=float, default=600.0, help="seconds")
    ap.add_argument("--cooldown", type=float, default=3.0)
    ap.add_argument("--gpu-index", default="",
                    help="sample this GPU with nvidia-smi (same host only)")
    ap.add_argument("--note", action="append", default=[],
                    help="free text stored in run_meta.json, e.g. --note ASR_MAX_BATCH=256")
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    base = a.url.rstrip("/")
    host = base.split("://", 1)[-1]
    ws_base = ("wss://" if base.startswith("https://") else "ws://") + host
    a.ws_url = f"{ws_base}{a.ws_path}?language={a.language}"
    a.health_url = f"{base}{a.health_path}"
    sys.exit(asyncio.run(main_async(a)))


if __name__ == "__main__":
    main()
