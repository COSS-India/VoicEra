#!/usr/bin/env python3
"""Measure how often TTS runs away, one request at a time, with no load.

A runaway is a response that does not stop by itself and is cut off by the
server's duration guard at (characters / 8) x 3 seconds of audio. Under the
concurrency test runaways and load are mixed together; this check isolates the
model's own rate at N=1 so the two can be told apart.

    python runaway_check.py --url http://HOST:8100 --language mr --n 200 \\
        --out-dir results/my-run

Two ways to send each request (same engine, same guard, same audio):

  --protocol http  POST /v1/audio/speech, what callers use. Runaways are judged
                   by audio length alone, since this path cannot say why a
                   stream stopped.
  --protocol ws    The Orpheus WebSocket (/tts/v1/tts/ws through the gateway).
                   Its closing `done` frame carries the server's own account of
                   every stream, which turns a rate into a diagnosis:
                     finish_reason     end_of_speech (the model stopped itself),
                                       text_eos (stopped on the text end token),
                                       max_tokens (the duration guard cut it)
                     soft_eos_ignored  how many text end tokens the server
                                       dropped as padding because too little
                                       audio existed yet (ORPHEUS_SOFT_TEXT_EOS)
                   The summary cross-tabulates the two, so it shows whether
                   runaways follow an ignored text end token.

Writes <out-dir>/runaway[_<label>]/: requests.jsonl (one row per request),
summary.json, summary.md, runaway_NNN.wav for every runaway, and the first
--save-normal normal clips (normal_NNN.wav) to compare against. The rate is
reported with a 95% Wilson confidence interval. Use --label and --note to keep
A/B runs with different server settings apart.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import wave
from collections import Counter
from pathlib import Path

import httpx
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import RequestLog, run_meta, say, stats, wilson, write_json  # noqa: E402
from tts_load import RATE, guard_cap_s, health, is_silent, resolve_text, synth  # noqa: E402


async def synth_ws(a: argparse.Namespace) -> dict:
    """One request over the Orpheus WebSocket, with the server's own metrics. Never raises."""
    req = {"text": a.text, "voice": a.voice, "language": a.language}
    if a.style:
        req["style"] = a.style
    pcm = bytearray()
    done: dict = {}
    err = None
    ttfa = None
    t0 = time.monotonic()
    try:
        async with websockets.connect(a.ws_url, max_size=None, open_timeout=15,
                                      close_timeout=5) as ws:
            await ws.send(json.dumps(req))
            while True:
                msg = await asyncio.wait_for(ws.recv(), a.request_timeout)
                if isinstance(msg, bytes | bytearray):
                    if ttfa is None:
                        ttfa = time.monotonic() - t0
                    pcm += msg
                    continue
                ev = json.loads(msg)
                if ev.get("type") == "done":
                    done = ev.get("metrics") or {}
                    break
                if ev.get("type") == "error":
                    err = f"server: {ev.get('message')}"[:200]
                    break
    except Exception as e:                                       # noqa: BLE001
        err = f"{type(e).__name__}: {e}"[:200]
    total = time.monotonic() - t0
    pcm = bytes(pcm[: len(pcm) - len(pcm) % 2])
    audio = len(pcm) / (RATE * 2)
    if err is None and not done:
        err = "stream ended without a done frame"
    if err is None and not pcm:
        err = "no audio returned"
    elif err is None and is_silent(pcm):
        err = "audio is silent"
    ok = err is None
    return {
        "ok": ok, "error": err,
        "ttfa_ms": round(ttfa * 1000, 1) if ok and ttfa is not None else None,
        "total_s": round(total, 4), "audio_s": round(audio, 4),
        "rtf": round(total / audio, 4) if ok and audio else None,
        "runaway": bool(ok and audio >= a.runaway_s),
        "finish_reason": done.get("finish_reason"),
        "soft_eos_ignored": done.get("soft_eos_ignored"),
        "server_tokens": done.get("tokens"),
        "server_audio_ms": done.get("audio_ms"),
        "server_rtf": done.get("rtf"),
        "_pcm": pcm,
    }


def save_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


def diagnosis(ok: list[dict]) -> dict:
    """Cross-tabulate the server's finish_reason and soft_eos_ignored (ws only)."""
    if not any(r.get("finish_reason") for r in ok):
        return {"note": "NOT AVAILABLE (http protocol, or server sent no metrics)"}

    def ignored(rows: list[dict]) -> dict:
        vals = [r.get("soft_eos_ignored") for r in rows if r.get("soft_eos_ignored") is not None]
        with_one = sum(1 for v in vals if v > 0)
        return {"requests": len(rows), "reported": len(vals), "with_ignored_text_eos": with_one,
                "share_with_ignored": round(with_one / len(vals), 4) if vals else None,
                "ignored_per_request": stats([float(v) for v in vals])}

    run = [r for r in ok if r["runaway"]]
    norm = [r for r in ok if not r["runaway"]]
    guard_cut = [r for r in ok if r.get("finish_reason") == "max_tokens"]
    return {
        "finish_reason_all": dict(Counter(r.get("finish_reason") for r in ok)),
        "finish_reason_runaways": dict(Counter(r.get("finish_reason") for r in run)),
        "finish_reason_normal": dict(Counter(r.get("finish_reason") for r in norm)),
        "server_runaways_max_tokens": len(guard_cut),
        "length_vs_server_disagree": sum(
            1 for r in ok if r["runaway"] != (r.get("finish_reason") == "max_tokens")),
        "soft_eos_runaways": ignored(run),
        "soft_eos_normal": ignored(norm),
    }


async def main_async(a: argparse.Namespace) -> int:
    out = Path(a.out_dir) / ("runaway_" + a.label if a.label else "runaway")
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
        target = a.ws_url if a.protocol == "ws" else a.speech_url
        say(f"{a.n} sequential requests over {a.protocol} ({target}), voice {a.voice}, "
            f"{len(a.text)} chars; guard cap {cap:.2f} s, runaway if audio >= {a.runaway_s} s")
        write_json(out / "run_meta.json", run_meta(a, h))
        log = RequestLog(out / "requests.jsonl")
        rows = []
        saved_normal = 0
        t_start = time.time()
        for i in range(1, a.n + 1):
            if a.protocol == "ws":
                r = await synth_ws(a)
            else:
                r = await synth(client, a, time.monotonic(), keep_audio=True)
                r.pop("_gaps", None)
            pcm = r.pop("_pcm", b"")
            r["i"] = i
            if r["runaway"]:
                save_wav(out / f"runaway_{i:03d}.wav", pcm)
            elif r["ok"] and saved_normal < a.save_normal:
                save_wav(out / f"normal_{i:03d}.wav", pcm)
                saved_normal += 1
            rows.append(r)
            log.write([r])
            if r["runaway"] or not r["ok"] or i % 20 == 0:
                k = sum(x["runaway"] for x in rows)
                tag = "RUNAWAY" if r["runaway"] else ("" if r["ok"] else f"ERROR {r['error']}")
                srv = ""
                if a.protocol == "ws":
                    srv = (f" finish={r.get('finish_reason')} "
                           f"soft_eos_ignored={r.get('soft_eos_ignored')}")
                say(f"  [{i:3d}/{a.n}] audio={r['audio_s']:6.2f}s rtf={r['rtf']}{srv}  "
                    f"runaways so far {k}  {tag}")

    ok = [r for r in rows if r["ok"]]
    run = [r for r in ok if r["runaway"]]
    norm = [r for r in ok if not r["runaway"]]
    k, n = len(run), len(ok)
    lo, hi = wilson(k, n)
    diag = diagnosis(ok)
    summary = {
        "when_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_start)),
        "protocol": a.protocol, "url": target, "label": a.label, "notes": a.note,
        "voice": a.voice, "language": a.language, "text": a.text, "style": a.style,
        "text_chars": len(a.text), "guard_cap_s": round(cap, 3),
        "runaway_threshold_s": a.runaway_s,
        "requests": len(rows), "ok": n, "errors": len(rows) - n, "runaways": k,
        "runaway_rate": round(k / n, 4) if n else None,
        "runaway_rate_95ci_wilson": [round(lo, 4), round(hi, 4)],
        "audio_s_normal": stats([r["audio_s"] for r in norm]),
        "audio_s_runaway": stats([r["audio_s"] for r in run]),
        "rtf_all": stats([r["rtf"] for r in ok]),
        "rtf_excluding_runaways": stats([r["rtf"] for r in norm]),
        "diagnosis": diag,
        "duration_s": round(time.time() - t_start, 1),
    }
    write_json(out / "summary.json", summary)
    (out / "summary.md").write_text(summary_md(a, summary, cap))
    say("\n" + (out / "summary.md").read_text() + f"\nwrote {out}")
    return 0


def summary_md(a: argparse.Namespace, s: dict, cap: float) -> str:
    k, n = s["runaways"], s["ok"]
    lo, hi = s["runaway_rate_95ci_wilson"]
    rate = f"{100 * k / n:.1f}%" if n else "--"
    md = (f"# TTS runaway check{' - ' + a.label if a.label else ''}\n\n"
          f"- {s['when_utc']} · {a.protocol} · voice {a.voice} · {a.language} · "
          f"{len(a.text)} characters\n"
          + (f"- Server notes: {'; '.join(a.note)}\n" if a.note else "")
          + f"- {s['requests']} sequential requests (N=1): {n} ok, {s['errors']} errors\n"
          f"- **Runaways (audio >= {a.runaway_s} s, guard cap {cap:.2f} s): {k} of {n} = {rate} "
          f"(95% CI {100 * lo:.1f}-{100 * hi:.1f}%)**\n"
          f"- Normal audio: p50 {s['audio_s_normal'].get('p50')} s, "
          f"max {s['audio_s_normal'].get('max')} s\n"
          f"- RTF all: p50 {s['rtf_all'].get('p50')}, p95 {s['rtf_all'].get('p95')}; "
          f"excluding runaways: p50 {s['rtf_excluding_runaways'].get('p50')}, "
          f"p95 {s['rtf_excluding_runaways'].get('p95')}\n")
    d = s["diagnosis"]
    if "note" in d:
        return md + f"\nServer-side diagnosis: {d['note']}. Rerun with `--protocol ws`.\n"
    sr, sn = d["soft_eos_runaways"], d["soft_eos_normal"]

    def share(x: dict) -> str:
        v = x["share_with_ignored"]
        return f"{x['with_ignored_text_eos']} of {x['reported']}" + \
            ("" if v is None else f" ({100 * v:.0f}%)")

    md += ("\n## Server-side diagnosis\n\n"
           "| | runaways | normal clips |\n|---|---|---|\n"
           f"| finish_reason | {fmt(d['finish_reason_runaways'])} | "
           f"{fmt(d['finish_reason_normal'])} |\n"
           f"| had >= 1 ignored text end token | {share(sr)} | {share(sn)} |\n"
           f"| ignored text end tokens per request, mean | "
           f"{sr['ignored_per_request'].get('mean', '--')} | "
           f"{sn['ignored_per_request'].get('mean', '--')} |\n\n"
           f"Guard cuts reported by the server (finish_reason = max_tokens): "
           f"{d['server_runaways_max_tokens']}; requests where the audio-length rule and "
           f"the server disagree: {d['length_vs_server_disagree']}.\n\n"
           "How to read it:\n\n"
           "- Runaways that mostly **had** an ignored text end token, while normal clips "
           "mostly did not, point at the soft text-eos rule: the model tried to stop, the "
           "server treated it as padding, and the model then never produced "
           "end-of-speech. Compare a run with `ORPHEUS_SOFT_TEXT_EOS=false`.\n"
           "- Runaways with **no** ignored text end token mean the model simply never tried "
           "to stop: a sampling problem. Compare lower `ORPHEUS_TEMPERATURE` or "
           "`ORPHEUS_REPETITION_PENALTY=1.1`.\n"
           "- Listen to `runaway_*.wav` against `normal_*.wav`: is the sentence complete "
           "before the babble starts?\n")
    return md


def fmt(c: dict) -> str:
    return ", ".join(f"{k}: {v}" for k, v in sorted(c.items(), key=lambda kv: -kv[1])) or "--"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8100")
    ap.add_argument("--protocol", default="http", choices=["http", "ws"])
    ap.add_argument("--speech-path", default="/v1/audio/speech")
    ap.add_argument("--ws-path", default="/tts/v1/tts/ws",
                    help="/tts/v1/tts/ws through the gateway, /v1/tts/ws on the container")
    ap.add_argument("--health-path", default="/tts/health")
    ap.add_argument("--voices-path", default="/tts/v1/voices")
    ap.add_argument("--language", default="mr")
    ap.add_argument("--voice", default="")
    ap.add_argument("--text", default="")
    ap.add_argument("--length", default="medium", choices=["short", "medium", "long"])
    ap.add_argument("--prompts", default="")
    ap.add_argument("--style", default="none")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--save-normal", type=int, default=5,
                    help="also save this many normal clips to compare against")
    ap.add_argument("--label", default="", help="suffix for the output folder, e.g. soft-eos-off")
    ap.add_argument("--request-timeout", type=float, default=120.0)
    ap.add_argument("--guard-chars-per-s", type=float, default=8.0)
    ap.add_argument("--guard-factor", type=float, default=3.0)
    ap.add_argument("--runaway-margin", type=float, default=0.01)
    ap.add_argument("--note", action="append", default=[],
                    help="server settings for this run, e.g. --note ORPHEUS_SOFT_TEXT_EOS=false")
    ap.add_argument("--out-dir", required=True)
    a = ap.parse_args()
    base = a.url.rstrip("/")
    a.speech_url, a.health_url, a.voices_url = (base + a.speech_path, base + a.health_path,
                                                base + a.voices_path)
    host = base.split("://", 1)[-1]
    a.ws_url = ("wss://" if base.startswith("https://") else "ws://") + host + a.ws_path
    a.text = resolve_text(a)
    sys.exit(asyncio.run(main_async(a)))


if __name__ == "__main__":
    main()
