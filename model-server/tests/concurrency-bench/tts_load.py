#!/usr/bin/env python3
"""Concurrency test for streaming TTS (OpenAI-style POST /v1/audio/speech, pcm).

Each request is one streaming synthesis of the same sentence. N requests are
started per round, either

  Test A  (--mode sync)    all N at the same instant, or
  Test B  (--mode random)  at N random times within --arrival-window seconds
                           (Poisson arrivals conditioned on exactly N; a fresh
                           draw every round).

Each N runs --rounds rounds and the rounds are pooled. Warm-up traffic runs
first and is discarded. Nothing stops early.

    python tts_load.py --url http://HOST:8100 --language mr --out-dir results/my-run

RTF (real-time factor) = time to generate the whole response / audio length.
Below 1 the audio arrives faster than it plays. TTFA (time to first audio) is
measured from the request's SCHEDULED start, so queueing counts.

Runaway generations. Orpheus has a server-side duration guard that stops a
response at (characters / 8) x 3 seconds of audio. A response that reaches the
guard is a runaway (the model did not stop by itself), not a normal answer.
It is flagged when its audio is within 1% of the guard, counted per cell and
logged per request. Runaways are still successful requests, so their RTF is
included; the report shows the runaway rate beside the verdict.
"""

from __future__ import annotations

import argparse
import array
import asyncio
import json
import random
import sys
import time
from pathlib import Path

import httpx

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

HERE = Path(__file__).resolve().parent
RATE = 24000                    # Orpheus pcm: 24 kHz mono int16


def guard_cap_s(text: str, chars_per_s: float, factor: float) -> float:
    """Audio length at which the server's duration guard cuts a response."""
    return len(text.strip()) / chars_per_s * factor


def is_silent(pcm: bytes) -> bool:
    if not pcm:
        return True
    a = array.array("h")
    a.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    step = max(1, len(a) // 2000)
    return max((abs(x) for x in a[::step]), default=0) < 64


async def synth(client: httpx.AsyncClient, a: argparse.Namespace, t_sched: float,
                keep_audio: bool = False) -> dict:
    """One streaming request, started at t_sched. Never raises."""
    await sleep_until(t_sched)
    body = {"input": a.text, "voice": a.voice, "language": a.language, "response_format": "pcm"}
    if a.style:
        body["style"] = a.style
    t_start = time.monotonic()
    ttfa = None
    last = t_start
    gaps: list[float] = []
    pcm = bytearray()
    err = None
    try:
        async with client.stream("POST", a.speech_url, json=body) as r:
            if r.status_code != 200:
                err = f"HTTP {r.status_code}: {(await r.aread())[:160].decode(errors='replace')}"
            else:
                async for chunk in r.aiter_raw():
                    if not chunk:
                        continue
                    now = time.monotonic()
                    if ttfa is None:
                        ttfa = now - t_start
                    else:
                        gaps.append(now - last)
                    last = now
                    pcm += chunk
    except Exception as e:                                       # noqa: BLE001
        err = f"{type(e).__name__}: {e}"[:200]
    total = time.monotonic() - t_start
    audio = (len(pcm) - len(pcm) % 2) / (RATE * 2)
    if err is None and not pcm:
        err = "no audio returned"
    elif err is None and is_silent(bytes(pcm)):
        err = "audio is silent"
    ok = err is None
    queue = max(0.0, t_start - t_sched)
    return {
        "ok": ok, "error": err,
        "ttfa_ms": round((queue + ttfa) * 1000, 1) if ok and ttfa is not None else None,
        "ttfa_service_ms": round(ttfa * 1000, 1) if ok and ttfa is not None else None,
        "client_start_late_ms": round(queue * 1000, 1),
        "total_s": round(total, 4), "audio_s": round(audio, 4),
        "rtf": round(total / audio, 4) if ok and audio else None,
        "chunks": len(gaps) + (1 if ttfa is not None else 0),
        "chunk_gap_ms_max": round(max(gaps) * 1000, 1) if gaps else None,
        "_gaps": gaps,
        "runaway": bool(ok and audio >= a.runaway_s),
        **({"_pcm": bytes(pcm[: len(pcm) - len(pcm) % 2])} if keep_audio else {}),
    }


async def health(client: httpx.AsyncClient, url: str) -> dict:
    try:
        return (await client.get(url, timeout=10)).json()
    except Exception:                                            # noqa: BLE001
        return {}


async def wait_idle(client: httpx.AsyncClient, url: str, timeout: float = 180) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        h = await health(client, url)
        if not h:
            return False
        if h.get("ready", True) and not h.get("streams_active"):
            return True
        await asyncio.sleep(0.5)
    return False


async def run_cell(client: httpx.AsyncClient, a: argparse.Namespace, mode: str, n: int,
                   log: RequestLog) -> dict:
    rng = random.Random(a.seed + 100 * n)
    rows: list[dict] = []
    await wait_idle(client, a.health_url)
    t_cell = time.monotonic()
    with GpuSampler(a.gpu_index) as gpu, LoopLag() as lag:
        for rnd in range(a.rounds):
            t0 = time.monotonic() + 0.5
            starts = batch_starts(n, mode, t0, a.arrival_window, rng)
            res = await asyncio.gather(*(synth(client, a, t) for t in starts))
            for t, r in zip(starts, res, strict=True):
                rows.append({"test": mode, "n": n, "round": rnd + 1,
                             "start_offset_ms": round((t - t0) * 1000, 1), **r})
            await wait_idle(client, a.health_url)
            await asyncio.sleep(1.0)
    wall = time.monotonic() - t_cell
    await asyncio.sleep(a.cooldown)
    gaps = [g * 1000 for r in rows for g in r.pop("_gaps")]
    log.write(rows)

    ok = [r for r in rows if r["ok"]]
    run = [r for r in ok if r["runaway"]]
    clean = [r for r in ok if not r["runaway"]]
    return {
        "n": n, "mode": mode, "rounds": a.rounds,
        "arrival_window_s": a.arrival_window if mode == "random" else 0.0,
        "requests": len(rows), "ok": len(ok), "failed": len(rows) - len(ok),
        "runaways": len(run), "runaway_rate": round(len(run) / len(ok), 4) if ok else None,
        "errors": sorted({r["error"] for r in rows if r["error"]})[:8],
        "rtf": stats([r["rtf"] for r in ok]),
        "rtf_excluding_runaways": stats([r["rtf"] for r in clean]),
        "ttfa_ms": stats([r["ttfa_ms"] for r in ok]),
        "ttfa_service_ms": stats([r["ttfa_service_ms"] for r in ok]),
        "client_start_late_ms": stats([r["client_start_late_ms"] for r in rows]),
        "chunk_gap_ms": stats(gaps),
        "audio_s": stats([r["audio_s"] for r in ok]),
        "audio_seconds_per_s": round(sum(r["audio_s"] for r in ok) / wall, 2) if wall else None,
        "loop_lag_ms": lag.summary(),
        "client_bound_suspected": lag.summary()["client_bound_suspected"],
        "gpu": gpu.summary(),
        "wall_s": round(wall, 1),
    }


def line(c: dict) -> str:
    r, t = c["rtf"], c["ttfa_ms"]
    return (f"ok={c['ok']}/{c['requests']} runaways={c['runaways']}  RTF p50={r.get('p50')} "
            f"p95={r.get('p95')} p99={r.get('p99')} max={r.get('max')}  "
            f"TTFA p95={t.get('p95')} ms"
            + ("  CLIENT-BOUND" if c["client_bound_suspected"] else ""))


async def main_async(a: argparse.Namespace) -> int:
    out = Path(a.out_dir) / "tts"
    out.mkdir(parents=True, exist_ok=True)
    timeout = httpx.Timeout(connect=10.0, read=a.request_timeout, write=30.0, pool=None)
    limits = httpx.Limits(max_connections=max(parse_levels(a.levels) + [64]) * 2,
                          max_keepalive_connections=128)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        h = await health(client, a.health_url)
        if not h:
            warn(f"no JSON from {a.health_url}; idle checks are off")
        elif h.get("ready") is False:
            raise SystemExit(f"TTS not ready: {h}")
        try:
            roster = (await client.get(a.voices_url, params={"language": a.language},
                                       timeout=15)).json()
            known = (roster.get(a.language) or {}).get("voices") or []
        except Exception:                                        # noqa: BLE001
            known = []
        if a.voice and known and a.voice not in known:
            raise SystemExit(f"voice {a.voice!r} not in the {a.language!r} roster: {known}")
        a.voice = a.voice or (known[0] if known else "")
        if not a.voice:
            raise SystemExit("no --voice given and the server's voice roster is unavailable")

        a.runaway_s = round(guard_cap_s(a.text, a.guard_chars_per_s, a.guard_factor)
                            * (1 - a.runaway_margin), 3)
        say(f"TTS  {a.speech_url}\n     voice {a.voice}, {a.language}, {len(a.text)} chars; "
            f"runaway if audio >= {a.runaway_s} s; levels {a.levels}; {a.rounds} rounds; "
            f"tests {a.mode}")
        write_json(out / "run_meta.json", run_meta(a, h))

        if a.warmup_singles or a.warmup_batches:
            say("\nwarm-up (discarded)")

            async def single() -> None:
                await synth(client, a, time.monotonic())

            async def batch(b: int) -> None:
                t0 = time.monotonic() + 0.5
                await asyncio.gather(*(synth(client, a, t0) for _ in range(b)))

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
                cell = await run_cell(client, a, mode, n, log)
                cells.append(cell)
                say(f"  N={n:<4} {line(cell)}")
                write_json(out / f"batch_{mode}.json",
                           {"model": "tts", "test": mode, "language": a.language,
                            "voice": a.voice, "text": a.text, "endpoint": a.speech_url,
                            "runaway_threshold_s": a.runaway_s, "cells": cells})
        meta = json.loads((out / "run_meta.json").read_text())
        meta["health_at_end"] = await health(client, a.health_url)
        write_json(out / "run_meta.json", meta)
    say(f"\nwrote {out}")
    return 0


def resolve_text(a: argparse.Namespace) -> str:
    if a.text:
        return a.text
    p = Path(a.prompts or HERE / "prompts" / f"{a.language}.json")
    if not p.exists():
        raise SystemExit(f"no --text given and no {p}; add a prompts file or pass --text")
    return json.loads(p.read_text())["tts_text"][a.length]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8100", help="gateway (or TTS) base URL")
    ap.add_argument("--speech-path", default="/v1/audio/speech")
    ap.add_argument("--health-path", default="/tts/health")
    ap.add_argument("--voices-path", default="/tts/v1/voices")
    ap.add_argument("--language", default="mr")
    ap.add_argument("--voice", default="", help="default: first voice in the server's roster")
    ap.add_argument("--text", default="",
                    help="sentence to speak; default from prompts/<lang>.json")
    ap.add_argument("--length", default="medium", choices=["short", "medium", "long"])
    ap.add_argument("--prompts", default="")
    ap.add_argument("--style", default="none", help="empty string to leave the field out")
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
    ap.add_argument("--request-timeout", type=float, default=300.0, help="seconds per request")
    ap.add_argument("--guard-chars-per-s", type=float, default=8.0)
    ap.add_argument("--guard-factor", type=float, default=3.0)
    ap.add_argument("--runaway-margin", type=float, default=0.01,
                    help="flag audio within this fraction of the guard cap")
    ap.add_argument("--gpu-index", default="",
                    help="sample this GPU with nvidia-smi (same host only)")
    ap.add_argument("--note", action="append", default=[],
                    help="free text stored in run_meta.json, e.g. --note ORPHEUS_MAX_NUM_SEQS=256")
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    base = a.url.rstrip("/")
    a.speech_url, a.health_url, a.voices_url = (base + a.speech_path, base + a.health_path,
                                                base + a.voices_path)
    a.text = resolve_text(a)
    sys.exit(asyncio.run(main_async(a)))


if __name__ == "__main__":
    main()
