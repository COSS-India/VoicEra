"""TTS load tester: latency, real-time factor and streaming behaviour.

Replaces the three WebSocket scripts that used to live in tts/tests/
(ws_smoke, multi_ws_smoke, hi_sequential_metrics). They were 90% the same code
against a protocol that no longer exists; this is one script with a
--concurrency knob.

    --concurrency 1     strictly sequential -- one request at a time
    --concurrency 16    fire all 16 at once, the shape a busy box actually sees

Run it against the gateway (default) or straight at the TTS container:

    python tests/bench_tts.py -n 20                       # sequential, 20 requests
    python tests/bench_tts.py -n 16 --concurrency 16      # concurrency target
    python tests/bench_tts.py --url http://localhost:8002 # skip the gateway
    python tests/bench_tts.py -n 8 --out-dir /tmp/wavs    # keep the audio
    python tests/bench_tts.py --sweep 1,2,4,8 -n 16       # one run per level

Rumik OSS-1 answers in 16-bit PCM and has its own voices and description
vocabulary, so point it at those:

    python tests/bench_tts.py --url http://127.0.0.1:8110 --format pcm \
        --voice Ira --description "professional, Hindi accent, steady pace" \
        --sweep 1,2,4,8,12,16 -n 24

What the numbers mean:
    ttft   time to first audio byte. This is what a caller hears as the pause
           before the bot speaks. Under ~300 ms feels natural.
    rtf    wall clock / audio duration. Below 1.0 means the model produces
           speech faster than it is played, so the stream never starves.
    gaps   time between audio chunks. A long gap mid-sentence is a stutter even
           when the overall rtf looks fine.

Needs nothing but httpx: no numpy, no scipy, so it runs in any container here.
"""

from __future__ import annotations

import argparse
import array
import asyncio
import re
import statistics
import struct
import sys
import time
import wave
from pathlib import Path

import httpx

DEFAULT_URL = "http://127.0.0.1:8100"
DEFAULT_DESCRIPTION = "A calm, clear voice speaking at a normal pace."

# Rotated through so a run is not one sentence measured N times.
SENTENCES: list[str] = [
    "नमस्ते! क्या आप मेरी आवाज़ साफ़ सुन पा रहे हैं?",
    "आज मौसम बहुत सुहावना है और हल्की हवा चल रही है।",
    "कृपया इस वाक्य को ध्यान से सुनें और फिर बताइए कि कैसा लगा।",
    "यह एक परीक्षण है ताकि हम समय और गुणवत्ता दोनों का आकलन कर सकें।",
    "धन्यवाद, आपका दिन शुभ हो और आगे भी संपर्क में रहिए।",
]


def _slug(text: str, max_len: int = 60) -> str:
    s = re.sub(r"\s+", "_", re.sub(r'[<>:"/\\|?*\n\r\t]', "_", text.strip()))
    return (s.strip("._") or "output")[:max_len]


def _write_wav(path: Path, samples: array.array, rate: int) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(b"".join(
            struct.pack("<h", max(-32768, min(32767, int(s * 32767)))) for s in samples))


async def run_one(client: httpx.AsyncClient, url: str, index: int, prompt: str,
                  args: argparse.Namespace) -> dict:
    """One synthesis, timed. Never raises -- a failure is a result too."""
    payload = {
        "input": prompt,
        "voice": args.voice or None,
        "instructions": args.description,
        "language": args.language,
        "response_format": args.format,
    }
    pcm = array.array("f")
    rate = 44100
    ttft = None
    gaps: list[float] = []
    t0 = time.monotonic()
    last = t0
    try:
        async with client.stream("POST", url, json=payload) as r:
            if r.status_code != 200:
                body = (await r.aread())[:200].decode(errors="replace")
                return {"index": index, "ok": False, "error": f"HTTP {r.status_code}: {body}"}
            rate = int(r.headers.get("X-Sample-Rate", rate))
            # Decode by what the server says it sent, never by what was asked
            # for: two TTS models here disagree on sample width, and guessing
            # wrong turns speech into noise with a plausible duration.
            fmt = (r.headers.get("X-Audio-Format") or args.format).lower()
            if fmt in ("pcm", "pcm_s16le"):
                width, code, scale = 2, "h", 1.0 / 32768.0
            elif fmt == "pcm_f32le":
                width, code, scale = 4, "f", 1.0
            else:
                return {"index": index, "ok": False,
                        "error": f"server sent {fmt!r}; this bench decodes raw PCM only"}
            # A chunk can end mid-sample; carry the tail or every later sample is noise.
            remainder = b""
            async for chunk in r.aiter_raw():
                if not chunk:
                    continue
                now = time.monotonic()
                if ttft is None:
                    ttft = now - t0
                else:
                    gaps.append(now - last)
                last = now
                buf = remainder + chunk
                usable = len(buf) - (len(buf) % width)
                remainder = buf[usable:]
                if usable:
                    samples = array.array(code)
                    samples.frombytes(buf[:usable])
                    pcm.extend(samples if scale == 1.0 else (s * scale for s in samples))
    except Exception as exc:                                    # noqa: BLE001
        return {"index": index, "ok": False, "error": f"{type(exc).__name__}: {exc}"}

    total = time.monotonic() - t0
    if not pcm:
        return {"index": index, "ok": False, "error": "no audio returned"}

    audio_s = len(pcm) / rate
    wav_path = None
    if args.out_dir:
        out = Path(args.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        wav_path = out / f"{index:03d}_{_slug(prompt)}.wav"
        _write_wav(wav_path, pcm, rate)

    return {
        "index": index, "ok": True, "prompt": prompt, "sample_rate": rate,
        "audio_s": audio_s, "ttft_s": ttft, "total_s": total,
        "rtf": total / audio_s if audio_s else None,
        "n_chunks": len(gaps) + 1, "gaps_s": gaps,
        "wav_path": str(wav_path) if wav_path else None,
    }


def _line(name: str, xs: list[float], unit: str) -> None:
    if not xs:
        print(f"  {name:<34} n/a")
        return
    xs = sorted(xs)
    p95 = xs[min(len(xs) - 1, int(len(xs) * 0.95))]
    print(f"  {name:<34} avg={statistics.fmean(xs):7.2f}{unit}  "
          f"min={xs[0]:7.2f}{unit}  p95={p95:7.2f}{unit}  max={xs[-1]:7.2f}{unit}")


def report(results: list[dict], args: argparse.Namespace, wall: float) -> int:
    oks = [r for r in results if r["ok"]]
    for r in results:
        if not r["ok"]:
            print(f"  [{r['index']:03d}] ERROR {r['error']}")
    if not oks:
        print("\nNo successful requests.")
        return 1

    ttft_ms = [r["ttft_s"] * 1000 for r in oks if r["ttft_s"] is not None]
    total_ms = [r["total_s"] * 1000 for r in oks]
    rtfs = [r["rtf"] for r in oks if r["rtf"] is not None]
    gap_ms = [g * 1000 for r in oks for g in r["gaps_s"]]
    chunks = [float(r["n_chunks"]) for r in oks]

    mode = "sequential" if args.concurrency == 1 else f"{args.concurrency} at once"
    print(f"\n--- summary ({mode}) ---")
    print(f"  {'requests':<34} {len(oks)}/{len(results)} ok   wall={wall:.2f}s   "
          f"throughput={len(oks) / wall:.2f} req/s")
    _line("time to first audio", ttft_ms, "ms")
    _line("total per request", total_ms, "ms")
    _line("audio duration", [r["audio_s"] for r in oks], "s")
    _line("realtime factor (total/audio)", rtfs, "x")
    _line("audio chunks per request", chunks, "")
    _line("gap between chunks", gap_ms, "ms")

    faster_than_realtime = sum(1 for x in rtfs if x < 1.0)
    print(f"\n  {faster_than_realtime}/{len(rtfs)} requests ran faster than real time "
          f"(rtf < 1). Anything slower will make the caller wait mid-sentence.")
    if args.out_dir:
        print(f"  wavs written to {args.out_dir} -- listen to a couple "
              "before trusting the numbers.")
    return 0 if faster_than_realtime == len(rtfs) and len(oks) == len(results) else 1


async def async_main(args: argparse.Namespace) -> int:
    url = args.url.rstrip("/")
    if not url.endswith("/v1/audio/speech"):
        url += "/v1/audio/speech"
    if not args.sweep:
        return (await run_level(url, args, args.concurrency))[0]

    rows, worst = [], 0
    for level in args.sweep:
        code, summary = await run_level(url, args, level)
        worst = max(worst, code)
        rows.append(summary)
    print("\n=== sweep ===")
    print(f"  {'conc':>4}  {'ok':>7}  {'ttfa p50':>9}  {'ttfa p95':>9}  {'rtf p50':>7}  "
          f"{'rtf p95':>7}  {'rtf max':>7}  {'gap p95':>8}  {'<1.0':>6}")
    for s in rows:
        print(f"  {s['conc']:>4}  {s['ok']:>7}  {s['ttfa_p50']:>7.0f}ms  {s['ttfa_p95']:>7.0f}ms  "
              f"{s['rtf_p50']:>7.2f}  {s['rtf_p95']:>7.2f}  {s['rtf_max']:>7.2f}  "
              f"{s['gap_p95']:>6.0f}ms  {s['realtime']:>6}")
    return worst


def _pct(xs: list[float], q: float) -> float:
    if not xs:
        return float("nan")
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * q))]


async def run_level(url: str, args: argparse.Namespace, concurrency: int) -> tuple[int, dict]:
    """One run at one concurrency level: the original single-run behaviour."""
    args.concurrency = concurrency
    prompts = [SENTENCES[i % len(SENTENCES)] for i in range(args.requests)]
    print(f"\nPOST {url}   {args.requests} requests, concurrency {args.concurrency}\n")

    sem = asyncio.Semaphore(args.concurrency)
    t0 = time.monotonic()
    async with httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0, read=None,
                                                       write=None, pool=5.0)) as client:
        async def guarded(i: int, prompt: str) -> dict:
            async with sem:
                if args.gap_s and args.concurrency == 1 and i:
                    await asyncio.sleep(args.gap_s)
                r = await run_one(client, url, i, prompt, args)
                if r["ok"]:
                    print(f"  [{i:03d}] ttft={r['ttft_s'] * 1000:7.1f}ms  "
                          f"total={r['total_s']:6.2f}s  audio={r['audio_s']:5.2f}s  "
                          f"rtf={r['rtf']:5.2f}  chunks={r['n_chunks']}")
                return r

        results = await asyncio.gather(*(guarded(i, p) for i, p in enumerate(prompts)))
    results = list(results)
    code = report(results, args, time.monotonic() - t0)
    oks = [r for r in results if r["ok"]]
    ttfa = [r["ttft_s"] * 1000 for r in oks if r["ttft_s"] is not None]
    rtfs = [r["rtf"] for r in oks if r["rtf"] is not None]
    gaps = [g * 1000 for r in oks for g in r["gaps_s"]]
    return code, {
        "conc": concurrency, "ok": f"{len(oks)}/{len(results)}",
        "ttfa_p50": _pct(ttfa, 0.5), "ttfa_p95": _pct(ttfa, 0.95),
        "rtf_p50": _pct(rtfs, 0.5), "rtf_p95": _pct(rtfs, 0.95),
        "rtf_max": max(rtfs) if rtfs else float("nan"), "gap_p95": _pct(gaps, 0.95),
        "realtime": f"{sum(1 for x in rtfs if x < 1.0)}/{len(rtfs)}",
    }


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default=DEFAULT_URL,
                   help=f"gateway or TTS base URL (default {DEFAULT_URL})")
    p.add_argument("-n", "--requests", type=int, default=20, help="how many requests (default 20)")
    p.add_argument("-c", "--concurrency", type=int, default=1,
                   help="requests in flight at once; 1 is sequential (default 1)")
    p.add_argument("--gap-s", type=float, default=0.0,
                   help="pause between sequential requests (ignored when concurrent)")
    p.add_argument("--voice", default="Divya", help="speaker preset (default Divya)")
    p.add_argument("--description", default=DEFAULT_DESCRIPTION, help="style instructions")
    p.add_argument("--language", default="hi", help="language tag (default hi)")
    p.add_argument("--format", default="pcm_f32le",
                   help="response_format to request: pcm_f32le (indic-parler, default) or "
                        "pcm (16-bit; orpheus, rumik-oss-1). Decoding follows X-Audio-Format.")
    p.add_argument("--sweep", default="",
                   help="comma-separated concurrency levels, e.g. 1,2,4,8: one run of -n "
                        "requests per level, then a summary table. Overrides -c.")
    p.add_argument("--out-dir", default="", help="write wavs here so you can listen to them")
    args = p.parse_args()

    if args.requests < 1:
        p.error("--requests must be >= 1")
    if args.concurrency < 1:
        p.error("--concurrency must be >= 1")
    try:
        args.sweep = [int(x) for x in args.sweep.split(",") if x.strip()]
    except ValueError:
        p.error("--sweep must be comma-separated integers, e.g. 1,2,4,8")
    if any(level < 1 for level in args.sweep):
        p.error("--sweep levels must be >= 1")
    sys.exit(asyncio.run(async_main(args)))


if __name__ == "__main__":
    main()
