"""Measure a running hima-asr server: transcripts, speed, and partial latency.

Runs inside the container, which already has numpy, soundfile and websockets:

    docker exec voicera_hima_test_stt python3 tools/probe.py post  clip.wav --language hi
    docker exec voicera_hima_test_stt python3 tools/probe.py live  clip.wav --language hi
    docker exec voicera_hima_test_stt python3 tools/probe.py live  clip.wav --sessions 8

Paths are inside the container; the model folder is mounted at /app, so a clip
copied into model-server/stt/hima-asr/ on the host is /app/<name> here.

post   one request per clip over POST /v1/audio/transcriptions. Reports the
       transcript, wall time and real-time factor (wall / audio duration).
live   streams each clip over /v1/realtime at real-time pace in 100 ms chunks,
       exactly as Pipecat would, then commits. Reports:
         first_partial  ms from the first audio sent to the first delta
         final          ms from commit to `completed` -- what a caller waits
                        after they stop talking
       With --sessions N, N streams run at once (the same clip, staggered by
       up to one chunk), and the report is the p50/p95 across them -- the
       number that says how many concurrent calls this card holds.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import statistics
import time
import urllib.request
import uuid

import numpy as np
import soundfile as sf

WIRE_RATE = 24000
CHUNK_MS = 100


def load(path: str, rate: int) -> np.ndarray:
    data, sr = sf.read(path, dtype="float32", always_2d=True)
    x = data.mean(axis=1)
    if sr != rate:
        n = int(len(x) * rate / sr)
        x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)
    return x


def to_wav_bytes(x: np.ndarray, rate: int) -> bytes:
    import io

    buf = io.BytesIO()
    sf.write(buf, x, rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


# ---- POST -------------------------------------------------------------------


def post_once(base: str, path: str, language: str) -> dict:
    audio = load(path, 16000)
    body_wav = to_wav_bytes(audio, 16000)
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\nhima-asr\r\n',
        f'--{boundary}\r\nContent-Disposition: form-data; name="language"\r\n\r\n{language}\r\n',
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="a.wav"\r\n'
        "Content-Type: audio/wav\r\n\r\n",
    ]
    body = "".join(parts).encode() + body_wav + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{base}/v1/audio/transcriptions",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as r:
        text = json.loads(r.read())["text"]
    wall = time.perf_counter() - t0
    dur = len(audio) / 16000
    return {
        "clip": path,
        "seconds": round(dur, 2),
        "wall_ms": round(wall * 1000),
        "rtf": round(wall / dur, 4),
        "text": text,
    }


# ---- Realtime ---------------------------------------------------------------


async def live_once(ws_url: str, audio24: np.ndarray, language: str, delay: float) -> dict:
    import websockets

    await asyncio.sleep(delay)
    pcm = (np.clip(audio24, -1, 1) * 32767).astype(np.int16)
    step = WIRE_RATE * CHUNK_MS // 1000
    out: dict = {"first_partial_ms": None, "final_ms": None, "text": "", "errors": []}
    async with websockets.connect(f"{ws_url}?intent=transcription", max_size=None) as ws:
        await ws.recv()  # session.created
        await ws.send(
            json.dumps(
                {
                    "type": "session.update",
                    "session": {
                        "type": "transcription",
                        "audio": {
                            "input": {
                                "format": {"type": "audio/pcm", "rate": WIRE_RATE},
                                "transcription": {"model": "hima-asr", "language": language},
                                "turn_detection": None,
                            }
                        },
                    },
                }
            )
        )
        while json.loads(await ws.recv())["type"] != "session.updated":
            pass

        t_start = time.perf_counter()
        t_commit = None
        done = asyncio.Event()

        async def reader():
            nonlocal t_commit
            async for raw in ws:
                evt = json.loads(raw)
                kind = evt["type"]
                now = time.perf_counter()
                if kind.endswith("transcription.delta") and out["first_partial_ms"] is None:
                    out["first_partial_ms"] = round((now - t_start) * 1000)
                elif kind.endswith("transcription.completed"):
                    out["text"] = evt.get("transcript", "")
                    if t_commit is not None:
                        out["final_ms"] = round((now - t_commit) * 1000)
                elif kind == "error":
                    out["errors"].append(evt["error"]["message"])
                elif kind == "input_audio_buffer.committed":
                    done.set()
                    return

        task = asyncio.create_task(reader())
        for i in range(0, len(pcm), step):
            chunk = pcm[i : i + step].tobytes()
            await ws.send(
                json.dumps(
                    {"type": "input_audio_buffer.append", "audio": base64.b64encode(chunk).decode()}
                )
            )
            # real-time pace, measured against the clock so drift does not build
            target = t_start + (i + step) / WIRE_RATE
            await asyncio.sleep(max(0.0, target - time.perf_counter()))
        t_commit = time.perf_counter()
        await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        await asyncio.wait_for(done.wait(), timeout=60)
        await task
    return out


def pct(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


async def live(args) -> None:
    ws_url = args.url.replace("http", "ws", 1) + "/v1/realtime"
    for path in args.clips:
        audio24 = load(path, WIRE_RATE)
        n = args.sessions
        res = await asyncio.gather(
            *[
                live_once(ws_url, audio24, args.language, i * CHUNK_MS / 1000 / max(n, 1))
                for i in range(n)
            ]
        )
        firsts = [r["first_partial_ms"] for r in res if r["first_partial_ms"] is not None]
        finals = [r["final_ms"] for r in res if r["final_ms"] is not None]
        report = {
            "clip": path,
            "seconds": round(len(audio24) / WIRE_RATE, 2),
            "sessions": n,
            "text": res[0]["text"],
            "errors": sorted({e for r in res for e in r["errors"]}),
        }
        if n == 1:
            report |= {
                "first_partial_ms": res[0]["first_partial_ms"],
                "final_ms": res[0]["final_ms"],
            }
        else:
            for name, xs in (("first_partial_ms", firsts), ("final_ms", finals)):
                if xs:
                    report[name] = {
                        "p50": pct(xs, 50),
                        "p95": pct(xs, 95),
                        "max": max(xs),
                        "mean": round(statistics.mean(xs)),
                    }
            report["completed"] = f"{len(finals)}/{n}"
        print(json.dumps(report, ensure_ascii=False, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("mode", choices=["post", "live"])
    ap.add_argument("clips", nargs="+", help="WAV/FLAC files (any rate, any channels)")
    ap.add_argument("--language", default="hi")
    ap.add_argument("--url", default="http://localhost:8001")
    ap.add_argument("--sessions", type=int, default=1, help="live: concurrent streams")
    args = ap.parse_args()

    if args.mode == "post":
        for path in args.clips:
            print(json.dumps(post_once(args.url, path, args.language), ensure_ascii=False))
    else:
        asyncio.run(live(args))


if __name__ == "__main__":
    main()
