#!/usr/bin/env python3
"""Measure how often TTS runs away, one request at a time, with no load.

A runaway is a response that does not stop by itself and is cut off by the
server's duration guard at (characters / 8) x 3 seconds of audio. Under the
concurrency test runaways and load are mixed together; this check isolates the
model's own rate at N=1 so the two can be told apart.

    python runaway_check.py --url http://HOST:8100 --language mr --n 200 \\
        --out-dir results/my-run

Writes <out-dir>/runaway/: requests.jsonl (one row per request), summary.json,
summary.md, and runaway_NNN.wav for every runaway so it can be listened to.
The rate is reported with a 95% Wilson confidence interval.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
import wave
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RequestLog, run_meta, say, stats, wilson, write_json  # noqa: E402
from tts_load import RATE, guard_cap_s, health, resolve_text, synth  # noqa: E402


async def main_async(a: argparse.Namespace) -> int:
    out = Path(a.out_dir) / "runaway"
    out.mkdir(parents=True, exist_ok=True)
    timeout = httpx.Timeout(connect=10.0, read=a.request_timeout, write=30.0, pool=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        h = await health(client, a.health_url)
        if h.get("ready") is False:
            raise SystemExit(f"TTS not ready: {h}")
        if not a.voice:
            roster = (await client.get(a.voices_url, params={"language": a.language},
                                       timeout=15)).json()
            a.voice = ((roster.get(a.language) or {}).get("voices") or [""])[0]
        cap = guard_cap_s(a.text, a.guard_chars_per_s, a.guard_factor)
        a.runaway_s = round(cap * (1 - a.runaway_margin), 3)
        say(f"{a.n} sequential requests, voice {a.voice}, {len(a.text)} chars; "
            f"guard cap {cap:.2f} s, runaway if audio >= {a.runaway_s} s")
        write_json(out / "run_meta.json", run_meta(a, h))
        log = RequestLog(out / "requests.jsonl")
        rows = []
        t_start = time.time()
        for i in range(1, a.n + 1):
            r = await synth(client, a, time.monotonic(), keep_audio=True)
            pcm = r.pop("_pcm", b"")
            r.pop("_gaps", None)
            r["i"] = i
            if r["runaway"]:
                with wave.open(str(out / f"runaway_{i:03d}.wav"), "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(RATE)
                    w.writeframes(pcm)
            rows.append(r)
            log.write([r])
            if r["runaway"] or not r["ok"] or i % 20 == 0:
                k = sum(x["runaway"] for x in rows)
                tag = "RUNAWAY" if r["runaway"] else ("" if r["ok"] else f"ERROR {r['error']}")
                say(f"  [{i:3d}/{a.n}] audio={r['audio_s']:6.2f}s rtf={r['rtf']} "
                    f"runaways so far {k}  {tag}")

    ok = [r for r in rows if r["ok"]]
    run = [r for r in ok if r["runaway"]]
    norm = [r for r in ok if not r["runaway"]]
    k, n = len(run), len(ok)
    lo, hi = wilson(k, n)
    summary = {
        "when_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_start)),
        "url": a.speech_url, "voice": a.voice, "language": a.language, "text": a.text,
        "text_chars": len(a.text), "guard_cap_s": round(cap, 3), "runaway_threshold_s": a.runaway_s,
        "requests": len(rows), "ok": n, "errors": len(rows) - n, "runaways": k,
        "runaway_rate": round(k / n, 4) if n else None,
        "runaway_rate_95ci_wilson": [round(lo, 4), round(hi, 4)],
        "audio_s_normal": stats([r["audio_s"] for r in norm]),
        "audio_s_runaway": stats([r["audio_s"] for r in run]),
        "rtf_all": stats([r["rtf"] for r in ok]),
        "rtf_excluding_runaways": stats([r["rtf"] for r in norm]),
        "duration_s": round(time.time() - t_start, 1),
    }
    write_json(out / "summary.json", summary)
    rate = f"{100 * k / n:.1f}%" if n else "--"
    md = (f"# TTS runaway check\n\n"
          f"- {summary['when_utc']} · voice {a.voice} · {a.language} · {len(a.text)} characters\n"
          f"- {len(rows)} sequential requests (N=1): {n} ok, {len(rows) - n} errors\n"
          f"- **Runaways (audio >= {a.runaway_s} s, guard cap {cap:.2f} s): {k} of {n} = {rate} "
          f"(95% CI {100 * lo:.1f}-{100 * hi:.1f}%)**\n"
          f"- Normal audio: p50 {summary['audio_s_normal'].get('p50')} s, "
          f"max {summary['audio_s_normal'].get('max')} s\n"
          f"- RTF all: p50 {summary['rtf_all'].get('p50')}, p95 {summary['rtf_all'].get('p95')}; "
          f"excluding runaways: p50 {summary['rtf_excluding_runaways'].get('p50')}, "
          f"p95 {summary['rtf_excluding_runaways'].get('p95')}\n")
    (out / "summary.md").write_text(md)
    say("\n" + md + f"wrote {out}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8100")
    ap.add_argument("--speech-path", default="/v1/audio/speech")
    ap.add_argument("--health-path", default="/tts/health")
    ap.add_argument("--voices-path", default="/tts/v1/voices")
    ap.add_argument("--language", default="mr")
    ap.add_argument("--voice", default="")
    ap.add_argument("--text", default="")
    ap.add_argument("--length", default="medium", choices=["short", "medium", "long"])
    ap.add_argument("--prompts", default="")
    ap.add_argument("--style", default="none")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--request-timeout", type=float, default=120.0)
    ap.add_argument("--guard-chars-per-s", type=float, default=8.0)
    ap.add_argument("--guard-factor", type=float, default=3.0)
    ap.add_argument("--runaway-margin", type=float, default=0.01)
    ap.add_argument("--note", action="append", default=[])
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    base = a.url.rstrip("/")
    a.speech_url, a.health_url, a.voices_url = (base + a.speech_path, base + a.health_path,
                                                base + a.voices_path)
    a.text = resolve_text(a)
    sys.exit(asyncio.run(main_async(a)))


if __name__ == "__main__":
    main()
