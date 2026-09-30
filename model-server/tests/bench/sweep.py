"""Drive the TTS load-test matrix and write one JSON per run.

Target: the OpenAI-spec streaming endpoint, `POST /v1/audio/speech` with
`response_format: pcm`, through the GATEWAY (default http://127.0.0.1:8100).
That is the published contract - the gateway exposes only three synthesis POSTs
and the model's native /v1/tts is not among them (405). Buffered synthesis is out
of scope; this deployment is for live streaming.

Two load models, because they answer different questions and only one of them is
honest about saturation:

  closed loop   A fixed pool of N callers: a new request starts only when an
                earlier one finishes. Finds the capacity ceiling.
  open loop     Requests arrive on a schedule fixed BEFORE the run and are
                launched whether or not the server is keeping up. This is what
                real traffic does.

Both measure latency from the SCHEDULED start, not from when a request actually
began. That distinction is the whole point: if you time from the actual start, a
request that waited four seconds for a slot records only its service time, the
queue delay vanishes, and p99 looks healthy exactly when the server is drowning.
That failure has a name - coordinated omission - and the STT bench next door
calls it out for the same reason (concurrency.py:18).

Usage:
    python sweep.py single                                  # one request at a time
    python sweep.py concurrency --levels 1,2,4,8,16,32,48
    python sweep.py arrivals --arrival poisson --rates 1,2,4,8,16
    python sweep.py arrivals --arrival sync --burst 8,16,32,64
    python sweep.py length | language | sustained
"""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
import random
import subprocess
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tts_client as tc                                          # noqa: E402
from gpu_sampler import GpuSampler                               # noqa: E402

# Single clause, no internal full stop / danda / comma. A second clause triggers a
# known runaway bug (~40% of runs, every style) that has nothing to do with load
# and would otherwise contaminate every cell.
PROMPTS = {
    "short":  "नमस्ते आज मौसम अच्छा है",
    "medium": "नमस्ते आज मौसम बहुत सुहावना है और हल्की ठंडी हवा चल रही है",
    "long":   "नमस्ते आज मौसम बहुत सुहावना है और हल्की ठंडी हवा चल रही है "
              "जिससे सुबह की सैर करने वालों को बहुत आनंद मिल रहा है और "
              "पार्क में बच्चे खेलते हुए दिखाई दे रहे हैं",
}
LANGUAGES = [("hi", None), ("bn", None), ("ta", None),
             ("te", None), ("mr", None), ("gu", None)]


def pct(xs: list[float], q: float) -> float | None:
    """Nearest-rank, no interpolation - matches stt/.../bench/metrics_lib.py:179."""
    if not xs:
        return None
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 4)


def stats(xs: list[float]) -> dict:
    xs = [x for x in xs if x is not None]
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "p50": pct(xs, .50), "p95": pct(xs, .95),
            "p99": pct(xs, .99), "min": round(min(xs), 4), "max": round(max(xs), 4)}


class Sched:
    """One request's schedule: when it should have started vs when it did."""

    __slots__ = ("result", "t_sched", "t_start")

    def __init__(self, result, t_sched, t_start):
        self.result, self.t_sched, self.t_start = result, t_sched, t_start

    @property
    def queue_delay_s(self) -> float:
        return max(0.0, self.t_start - self.t_sched)

    @property
    def ttfa_from_sched_s(self) -> float | None:
        if self.result.ttfa_s is None:
            return None
        return self.queue_delay_s + self.result.ttfa_s


def summarise(rows: list[Sched]) -> dict:
    """Aggregate one cell. Muted runs are counted but excluded from the numbers."""
    res = [s.result for s in rows]
    ok = [s for s in rows if s.result.ok]
    clean = [s for s in ok if not s.result.muted]
    r = [s.result for s in clean]
    return {
        "requests": len(rows),
        "ok": len(ok),
        "failed": len(rows) - len(ok),
        "muted": sum(1 for s in ok if s.result.muted),
        "errors": sorted({x.error for x in res if x.error})[:5],
        # What the caller experiences: measured from the scheduled arrival.
        "ttfa_ms": stats([s.ttfa_from_sched_s * 1000 for s in clean
                          if s.ttfa_from_sched_s is not None]),
        # Service time alone, for comparison with the scheduled figure above.
        "ttfa_service_ms": stats([x.ttfa_s * 1000 for x in r if x.ttfa_s is not None]),
        "queue_delay_ms": stats([s.queue_delay_s * 1000 for s in clean]),
        "total_s": stats([x.total_s for x in r]),
        "audio_s": stats([x.audio_s for x in r]),
        "rtf": stats([x.rtf for x in r if x.rtf]),
        "chunk_gap_ms": stats([g * 1000 for x in r for g in x.gaps_s]),
        "chunks": stats([float(x.n_chunks) for x in r]),
        "audio_seconds_total": round(sum(x.audio_s for x in r), 2),
    }


async def metrics(client, base) -> dict:
    try:
        r = await client.get(f"{base}/tts/metrics", timeout=10)
        return r.json() if r.status_code == 200 else {}
    except Exception:                                            # noqa: BLE001
        return {}


async def wait_idle(client, base, timeout: float = 180.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            h = (await client.get(f"{base}/tts/health", timeout=10)).json()
            if h.get("ready") and not h.get("streams_active"):
                return True
        except Exception:                                        # noqa: BLE001
            pass
        await asyncio.sleep(0.5)
    return False


async def one(client, args, text, voice, language) -> tc.Result:
    kw = dict(voice=voice, language=language, style=args.style, max_tokens=args.max_tokens)
    if args.protocol == "ws":
        return await tc.synth_ws(args.ws_url, text, **kw)
    fn = {"http": tc.synth_http, "sse": tc.synth_sse}[args.protocol]
    return await fn(client, args.url, text, **kw)


def schedule(n: int, mode: str, *, t0: float, rate: float, window: float,
             seed: int) -> list[float]:
    """Fix every arrival time before the run - see the coordinated-omission note."""
    rng = random.Random(seed)
    if mode == "sync":
        return [t0] * n                       # the artificial herd; a real worst case
    if mode == "poisson":
        out, t = [], t0
        for _ in range(n):
            t += rng.expovariate(rate) if rate > 0 else 0.0
            out.append(t)
        return out
    if mode == "stagger":
        return [t0 + i / rate for i in range(n)] if rate > 0 else [t0] * n
    return [t0] * n                            # closed loop: gated by the semaphore


async def run_cell(client, args, *, n, text, voice, language,
                   concurrency: int = 0, mode: str = "closed",
                   rate: float = 0.0, label: str = "") -> dict:
    """One condition. Warm up, discard, then measure n requests."""
    await one(client, args, text, voice, language)               # warm-up, discarded
    await wait_idle(client, args.url)
    before = await metrics(client, args.url)

    t0 = time.monotonic() + 0.5          # a beat so every task is scheduled first
    starts = schedule(n, mode, t0=t0, rate=rate, window=args.window, seed=args.seed)
    sem = asyncio.Semaphore(concurrency) if mode == "closed" and concurrency else None

    inflight = 0
    depth: list[int] = []

    async def launch(t_sched: float) -> Sched:
        nonlocal inflight
        delay = t_sched - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        if sem is not None:
            await sem.acquire()
        t_start = time.monotonic()
        if sem is not None:
            # Closed loop has no queue by construction: a worker issues its next
            # request only once it is free, so waiting for a slot IS the model,
            # not a delay the server imposed. Re-anchor the schedule to the
            # actual start so ttfa means service time here. Open loop keeps its
            # fixed schedule - that is where queue delay is real and must be
            # counted (see the coordinated-omission note at the top).
            t_sched = t_start
        inflight += 1
        try:
            r = await one(client, args, text, voice, language)
        finally:
            inflight -= 1
            if sem is not None:
                sem.release()
        return Sched(r, t_sched, t_start)

    async def sample_depth():
        try:
            while True:
                depth.append(inflight)
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass

    sampler = GpuSampler(10.0)
    watcher = asyncio.ensure_future(sample_depth())
    with sampler:
        rows = await asyncio.gather(*(launch(t) for t in starts))
    watcher.cancel()
    wall = time.monotonic() - t0
    after = await metrics(client, args.url)
    await wait_idle(client, args.url)

    cell = summarise(list(rows))
    cell.update({
        "label": label,
        "mode": mode,
        "concurrency": concurrency or None,
        "arrival_rate_per_s": rate or None,
        "wall_s": round(wall, 3),
        "requests_per_s": round(cell["ok"] / wall, 3) if wall else None,
        "audio_seconds_per_s": round(cell["audio_seconds_total"] / wall, 2) if wall else None,
        "queue_depth": {"p50": pct([float(d) for d in depth], .50),
                        "p95": pct([float(d) for d in depth], .95),
                        "max": max(depth) if depth else None},
        "server_counters": {
            "requests_delta": after.get("requests_total", 0) - before.get("requests_total", 0),
            "errors_delta": after.get("errors_total", 0) - before.get("errors_total", 0),
        },
        "gpu": sampler.summary(),
    })
    # A run where the driver itself fell behind describes the client, not the server.
    qd = cell["queue_delay_ms"].get("p95") or 0
    util = (cell["gpu"].get("utilization.gpu") or {}).get("p50") or 0
    cell["client_bound_suspected"] = bool(mode != "closed" and qd > 500 and util < 40)
    return cell


def resolve_voice(base, language, wanted):
    r = httpx.get(f"{base}/tts/v1/voices", params={"language": language}, timeout=15)
    r.raise_for_status()
    voices = r.json().get(language, {}).get("voices") or []
    if not voices:
        raise SystemExit(f"no voices for {language!r}")
    if wanted and wanted not in voices:
        raise SystemExit(f"voice {wanted!r} not in {language!r} roster: {voices}")
    return wanted or voices[0]


def environment(base) -> dict:
    env = {"host": platform.node(),
           "when_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "gateway": base, "endpoint": "POST /v1/audio/speech (response_format=pcm)"}
    try:
        env["health"] = httpx.get(f"{base}/tts/health", timeout=10).json()
    except Exception:                                            # noqa: BLE001
        env["health"] = "unreachable"
    for key, cmd in (("gpu", "nvidia-smi --query-gpu=name,memory.total,driver_version,"
                             "compute_cap --format=csv,noheader"),):
        try:
            env[key] = subprocess.run(cmd.split(), capture_output=True, text=True,
                                      timeout=10).stdout.strip()
        except Exception:                                        # noqa: BLE001
            env[key] = "NOT MEASURED"
    for var in ("ORPHEUS_GPU_MEMORY_UTILIZATION", "ORPHEUS_MAX_NUM_SEQS",
                "ORPHEUS_DECODER_MAX_BATCH", "ORPHEUS_MAX_TOKENS_DEFAULT",
                "ORPHEUS_TEMPERATURE", "ORPHEUS_REPETITION_PENALTY",
                "ORPHEUS_QUANTIZATION", "ORPHEUS_MAX_MODEL_LEN"):
        try:
            out = subprocess.run(["docker", "exec", "voicera_model_tts", "printenv", var],
                                 capture_output=True, text=True, timeout=10).stdout.strip()
            env.setdefault("engine_env", {})[var] = out or "(unset)"
        except Exception:                                        # noqa: BLE001
            pass
    try:
        log = subprocess.run(["docker", "logs", "voicera_model_tts"], capture_output=True,
                             text=True, timeout=20).stdout + \
              subprocess.run(["docker", "logs", "voicera_model_tts"], capture_output=True,
                             text=True, timeout=20).stderr
        for line in log.splitlines():
            if "KV cache" in line or "Maximum concurrency" in line:
                env.setdefault("kv_cache_lines", []).append(line.split("] ")[-1].strip())
    except Exception:                                            # noqa: BLE001
        pass
    return env


def line(cell) -> str:
    t, r = cell["ttfa_ms"], cell["rtf"]
    return (f"ok={cell['ok']}/{cell['requests']} muted={cell['muted']} "
            f"ttfa p50={t.get('p50')} p95={t.get('p95')} p99={t.get('p99')}ms  "
            f"rtf p50={r.get('p50')} p95={r.get('p95')}  "
            f"audio_s/s={cell['audio_seconds_per_s']} qdepth={cell['queue_depth']['max']}")


async def main_async(args) -> int:
    args.voice = resolve_voice(args.url, args.language, args.voice or None)
    out = {"suite": args.suite, "protocol": args.protocol, "style": args.style or "(default)",
           "voice": args.voice, "language": args.language, "max_tokens": args.max_tokens,
           "seed": args.seed, "environment": environment(args.url), "cells": []}
    print(f"suite={args.suite} endpoint={args.protocol} voice={args.voice} "
          f"style={args.style or '(default)'} -> {args.out}\n")

    timeout = httpx.Timeout(connect=10.0, read=None, write=None, pool=10.0)
    limits = httpx.Limits(max_connections=512, max_keepalive_connections=128)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        if not await wait_idle(client, args.url):
            print("server not idle/ready", file=sys.stderr)
            return 1
        P = PROMPTS[args.length]

        if args.suite == "single":
            cell = await run_cell(client, args, n=args.requests, text=P, voice=args.voice,
                                  language=args.language, concurrency=1, label="c=1")
            out["cells"].append(cell); print("  " + line(cell))

        elif args.suite == "concurrency":
            for lv in [int(x) for x in args.levels.split(",")]:
                cell = await run_cell(client, args, n=max(args.requests, lv), text=P,
                                      voice=args.voice, language=args.language,
                                      concurrency=lv, label=f"c={lv}")
                out["cells"].append(cell); print(f"  c={lv:<4} " + line(cell))

        elif args.suite == "arrivals":
            if args.arrival == "sync":
                for b in [int(x) for x in args.burst.split(",")]:
                    cell = await run_cell(client, args, n=b, text=P, voice=args.voice,
                                          language=args.language, mode="sync",
                                          label=f"burst={b}")
                    out["cells"].append(cell); print(f"  burst={b:<4} " + line(cell))
            else:
                for rate in [float(x) for x in args.rates.split(",")]:
                    n = max(args.requests, int(rate * args.window))
                    cell = await run_cell(client, args, n=n, text=P, voice=args.voice,
                                          language=args.language, mode=args.arrival,
                                          rate=rate, label=f"{args.arrival}@{rate}/s")
                    out["cells"].append(cell)
                    print(f"  {rate:>4}/s " + line(cell)
                          + ("  CLIENT-BOUND" if cell["client_bound_suspected"] else ""))

        elif args.suite == "length":
            for name, text in PROMPTS.items():
                cell = await run_cell(client, args, n=args.requests, text=text,
                                      voice=args.voice, language=args.language,
                                      concurrency=args.concurrency, label=name)
                cell["chars"] = len(text)
                out["cells"].append(cell); print(f"  {name:<7} chars={len(text):<4} " + line(cell))

        elif args.suite == "language":
            roster = httpx.get(f"{args.url}/tts/v1/languages", timeout=15).json()
            for lang, want in LANGUAGES:
                entry = next((e for e in roster if e.get("code") == lang), None)
                if not entry or not entry.get("sample"):
                    print(f"  {lang:<4} skipped (no sample text)"); continue
                v = resolve_voice(args.url, lang, want)
                cell = await run_cell(client, args, n=args.requests, text=entry["sample"],
                                      voice=v, language=lang,
                                      concurrency=args.concurrency, label=lang)
                cell.update({"voice": v, "chars": len(entry["sample"])})
                out["cells"].append(cell); print(f"  {lang:<4} {v:<10} " + line(cell))

        elif args.suite == "sustained":
            end = time.monotonic() + args.seconds
            while time.monotonic() < end:
                cell = await run_cell(client, args, n=args.concurrency * 2, text=P,
                                      voice=args.voice, language=args.language,
                                      concurrency=args.concurrency,
                                      label=f"wave{len(out['cells'])}")
                out["cells"].append(cell); print(f"  {cell['label']:<8} " + line(cell))
            half = len(out["cells"]) // 2 or 1
            def m(ws):
                v = [w["ttfa_ms"].get("p95") for w in ws if w["ttfa_ms"].get("p95")]
                return round(sum(v) / len(v), 1) if v else None
            out["drift"] = {"first_half_ttfa_p95_ms": m(out["cells"][:half]),
                            "second_half_ttfa_p95_ms": m(out["cells"][half:])}

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(f"\nwrote {args.out}")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("suite", choices=["single", "concurrency", "arrivals", "length",
                                     "language", "sustained"])
    p.add_argument("--url", default="http://127.0.0.1:8100")
    p.add_argument("--ws-url", default="ws://127.0.0.1:8100/tts/v1/tts/ws")
    p.add_argument("--protocol", default="http", choices=["http", "sse", "ws"],
                   help="default http = the OpenAI-spec streaming endpoint")
    p.add_argument("-n", "--requests", type=int, default=20)
    p.add_argument("-c", "--concurrency", type=int, default=1)
    p.add_argument("--levels", default="1,2,4,8,12,16,24,32,48,64")
    p.add_argument("--arrival", default="poisson", choices=["poisson", "stagger", "sync"])
    p.add_argument("--rates", default="1,2,4,8,12,16")
    p.add_argument("--burst", default="8,16,32,64")
    p.add_argument("--window", type=float, default=10.0, help="open-loop run length target")
    p.add_argument("--seed", type=int, default=1234)
    p.add_argument("--language", default="hi")
    p.add_argument("--voice", default="")
    p.add_argument("--style", default="none")
    p.add_argument("--length", default="medium", choices=list(PROMPTS))
    p.add_argument("--max-tokens", type=int, default=0)
    p.add_argument("--seconds", type=float, default=600.0)
    p.add_argument("--out", default="")
    args = p.parse_args()
    if not args.out:
        args.out = f"results/{args.suite}_{time.strftime('%Y%m%d-%H%M%S')}.json"
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
