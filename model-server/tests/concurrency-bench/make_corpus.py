#!/usr/bin/env python3
"""Build the audio corpus the STT test streams.

Two ways to get one; both end in the same manifest.json that stt_load.py reads.

  synth    Synthesise the sentences in prompts/<lang>.json with any running
           Orpheus (POST /v1/audio/speech). Every clip is its own reference
           transcript, so the STT test can report accuracy (CER) under load.

               python make_corpus.py synth --tts-url http://HOST:8100 \\
                   --language mr --voices Anagha,Chinmay --out corpus/

  import   Use recordings you already have: a folder of WAV files plus a CSV
           with columns  file,text[,bucket] . Clips are converted to 16 kHz mono
           int16. Without a bucket column, clips are bucketed by duration
           (short < 3.5 s <= medium < 10 s <= long).

               python make_corpus.py import --wav-dir my_clips/ \\
                   --transcripts my_clips/transcripts.csv --language mr --out corpus/

Buckets: short (~2-3 s), medium (~4-7 s), long (~15-20 s). With `synth`, a long
clip is three medium clips from the same voice joined with 400 ms of silence,
because asking Orpheus for one multi-clause sentence risks the runaway bug.

Validation (synth): a clip must not be silent and its duration must sit within
[--min-ratio, --max-ratio] x the time its text should take at 8 characters per
second. A failing clip is re-synthesised up to 3 times, then dropped and listed
in the manifest. A babbled clip would poison every CER number downstream.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
import wave
from pathlib import Path

import httpx
import numpy as np
from scipy.signal import resample_poly

HERE = Path(__file__).resolve().parent
TTS_RATE = 24000
RATE = 16000
CHARS_PER_S = 8.0


# --------------------------------------------------------------------------- audio helpers
def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return x
    g = np.gcd(src, dst)
    return resample_poly(x, dst // g, src // g)


def write_wav(path: Path, x16k: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes((np.clip(x16k, -1.0, 1.0) * 32767).astype(np.int16).tobytes())


def read_wav(path: Path) -> np.ndarray:
    """Any PCM WAV (8/16/24/32-bit int, mono or multi-channel) -> 16 kHz mono float."""
    with wave.open(str(path), "rb") as w:
        ch, width, sr = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width == 1:
        x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128) / 128
    elif width == 2:
        x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768
    elif width == 3:
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3)
        v = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8)
             | (b[:, 2].astype(np.int32) << 16))
        x = (np.where(v >= 1 << 23, v - (1 << 24), v)).astype(np.float32) / (1 << 23)
    elif width == 4:
        x = np.frombuffer(raw, "<i4").astype(np.float32) / (1 << 31)
    else:
        raise ValueError(f"{path}: unsupported sample width {width}")
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return resample(x, sr, RATE)


def expected_s(text: str) -> float:
    return len(text.strip()) / CHARS_PER_S


def bucket_for(dur: float) -> str:
    return "short" if dur < 3.5 else ("medium" if dur < 10.0 else "long")


def save_manifest(out: Path, language: str, source: str, clips: list, dropped: list,
                  extra: dict | None = None) -> int:
    by = {b: sum(1 for m in clips if m["bucket"] == b) for b in ("short", "medium", "long")}
    (out / "manifest.json").write_text(json.dumps(
        {"language": language, "sample_rate": RATE, "source": source, **(extra or {}),
         "counts": by, "clips": clips, "dropped": dropped}, indent=2, ensure_ascii=False))
    print(f"\nwrote {len(clips)} clips {by}, dropped {len(dropped)} -> {out / 'manifest.json'}",
          flush=True)
    return 0 if clips else 2


# --------------------------------------------------------------------------- synth
async def synth_one(client: httpx.AsyncClient, base: str, text: str, voice: str,
                    language: str) -> np.ndarray:
    body = {"input": text, "voice": voice, "language": language, "response_format": "pcm"}
    pcm = bytearray()
    async with client.stream("POST", f"{base}/v1/audio/speech", json=body) as r:
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {(await r.aread())[:200]!r}")
        async for chunk in r.aiter_raw():
            pcm += chunk
    pcm = bytes(pcm[: len(pcm) - len(pcm) % 2])
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def check(x: np.ndarray, text: str, lo: float, hi: float) -> str | None:
    if x.size == 0 or float(np.max(np.abs(x))) < 64 / 32768:
        return "silent"
    dur, exp = x.size / TTS_RATE, expected_s(text)
    if dur < lo * exp:
        return f"too short ({dur:.1f}s vs ~{exp:.1f}s)"
    if dur > hi * exp:
        return f"too long, likely runaway ({dur:.1f}s vs ~{exp:.1f}s)"
    return None


async def cmd_synth(a: argparse.Namespace) -> int:
    prompts = json.loads(Path(a.prompts or HERE / "prompts" / f"{a.language}.json").read_text())
    corpus = prompts["corpus"]
    short, medium = corpus.get("short", []), corpus.get("medium", [])
    groups = corpus.get("long_groups") or []
    out = Path(a.out)
    (out / "clips").mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        roster = (await client.get(f"{a.tts_url}/tts/v1/voices",
                                   params={"language": a.language}, timeout=15)).json()
        known = (roster.get(a.language) or {}).get("voices") or []
        voices = a.voices.split(",") if a.voices else known[:2]
        missing = [v for v in voices if known and v not in known]
        if not voices or missing:
            raise SystemExit(f"voices {missing or voices} not in the {a.language!r} "
                             f"roster: {known}")

        jobs = [("short", i, t, v) for v in voices for i, t in enumerate(short)] + \
               [("medium", i, t, v) for v in voices for i, t in enumerate(medium)]
        sem = asyncio.Semaphore(a.concurrency)
        good: dict[tuple, np.ndarray] = {}
        dropped: list[dict] = []

        async def run(bucket: str, i: int, text: str, voice: str) -> None:
            async with sem:
                why = None
                for _ in range(3):
                    try:
                        x = await synth_one(client, a.tts_url, text, voice, a.language)
                        why = check(x, text, a.min_ratio, a.max_ratio)
                    except Exception as e:                       # noqa: BLE001
                        why = f"{type(e).__name__}: {e}"
                    if why is None:
                        good[(bucket, i, voice)] = x
                        print(f"  ok    {bucket:<6} {voice:<10} #{i:02d} {x.size / TTS_RATE:5.2f}s",
                              flush=True)
                        return
                    print(f"  retry {bucket:<6} {voice:<10} #{i:02d}: {why}", flush=True)
                dropped.append({"bucket": bucket, "idx": i, "voice": voice, "why": why})

        await asyncio.gather(*(run(*j) for j in jobs))

    clips: list[dict] = []

    def emit(cid: str, bucket: str, voice: str, text: str, x24: np.ndarray) -> None:
        x16 = resample(x24, TTS_RATE, RATE)
        p = out / "clips" / f"{cid}.wav"
        write_wav(p, x16)
        clips.append({"id": cid, "bucket": bucket, "voice": voice, "text": text,
                      "duration_s": round(x16.size / RATE, 3), "path": f"clips/{cid}.wav"})

    for (bucket, i, voice), x in sorted(good.items()):
        text = (short if bucket == "short" else medium)[i]
        emit(f"{bucket}_{voice}_{i:02d}", bucket, voice, text, x)

    gap = np.zeros(int(0.4 * TTS_RATE), dtype=np.float32)
    for voice in voices:
        for g, idxs in enumerate(groups):
            parts = [good.get(("medium", i, voice)) for i in idxs]
            if any(p is None for p in parts):
                dropped.append({"bucket": "long", "idx": g, "voice": voice,
                                "why": "a medium part was dropped"})
                continue
            x = np.concatenate([np.concatenate([p, gap]) for p in parts])[: -gap.size]
            emit(f"long_{voice}_{g:02d}", "long", voice, " ".join(medium[i] for i in idxs), x)

    return save_manifest(out, a.language, f"Orpheus via {a.tts_url}", clips, dropped,
                         {"voices": voices})


# --------------------------------------------------------------------------- import
def cmd_import(a: argparse.Namespace) -> int:
    src = Path(a.wav_dir)
    out = Path(a.out)
    (out / "clips").mkdir(parents=True, exist_ok=True)
    clips: list[dict] = []
    dropped: list[dict] = []
    with open(a.transcripts, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows or not {"file", "text"} <= set(rows[0]):
        raise SystemExit("transcripts CSV needs a header with at least: file,text")
    for i, r in enumerate(rows):
        path = src / r["file"]
        try:
            x = read_wav(path)
        except Exception as e:                                   # noqa: BLE001
            dropped.append({"file": r["file"], "why": f"{type(e).__name__}: {e}"})
            continue
        if x.size == 0 or float(np.max(np.abs(x))) < 64 / 32768:
            dropped.append({"file": r["file"], "why": "silent"})
            continue
        dur = x.size / RATE
        bucket = (r.get("bucket") or "").strip() or bucket_for(dur)
        cid = f"{bucket}_{i:04d}_{Path(r['file']).stem}"[:80]
        write_wav(out / "clips" / f"{cid}.wav", x)
        clips.append({"id": cid, "bucket": bucket, "text": r["text"].strip(),
                      "duration_s": round(dur, 3), "path": f"clips/{cid}.wav",
                      "source_file": r["file"]})
    return save_manifest(out, a.language, f"imported from {src}", clips, dropped)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("synth", help="synthesise clips with a running Orpheus")
    s.add_argument("--tts-url", required=True, help="base URL serving /v1/audio/speech")
    s.add_argument("--language", default="mr")
    s.add_argument("--voices", default="", help="comma-separated; default: first two in roster")
    s.add_argument("--prompts", default="", help="default: prompts/<language>.json")
    s.add_argument("--concurrency", type=int, default=4)
    s.add_argument("--min-ratio", type=float, default=0.25)
    s.add_argument("--max-ratio", type=float, default=2.0)
    s.add_argument("--out", required=True)
    i = sub.add_parser("import", help="use your own WAV recordings")
    i.add_argument("--wav-dir", required=True)
    i.add_argument("--transcripts", required=True, help="CSV with columns file,text[,bucket]")
    i.add_argument("--language", required=True)
    i.add_argument("--out", required=True)
    a = ap.parse_args()
    sys.exit(asyncio.run(cmd_synth(a)) if a.cmd == "synth" else cmd_import(a))


if __name__ == "__main__":
    main()
