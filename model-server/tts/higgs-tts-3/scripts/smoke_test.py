"""Smoke-test a running Higgs TTS 3 adapter, and print a report to paste back.

Standard library only, so it runs on the GPU host as is:

    python3 tts/higgs-tts-3/scripts/smoke_test.py                     # standalone stack
    python3 tts/higgs-tts-3/scripts/smoke_test.py --url http://127.0.0.1:8202 --gpu 1

What it checks, in order, each a question the first hardware run has to answer
(see the folder README, "Not yet run on hardware"):

 1. it comes up: /health, waiting through the first-start download
 2. GPU memory: nvidia-smi before/after, against the overlay's caps
 3. speech in several languages: time-to-first-audio, RTF, and a .wav of each
    to LISTEN to (the numbers cannot tell you it sounds right)
 4. the contract: tags, speed, inline sfx/pauses, every response_format, SSE
 5. refusals: free-text instructions and unknown voices are 400s
 6. concurrency: per-stream TTFA and RTF at 1, 4 and 8 parallel requests
 7. barge-in: hang up mid-utterance, then check the sidecar logged an abort

Writes the audio and report.json into --out (default ./higgs-smoke-out).
"""
from __future__ import annotations

import argparse
import base64
import http.client
import json
import shutil
import statistics
import subprocess
import sys
import threading
import time
import urllib.parse
import wave
from pathlib import Path

RATE = 24000

#: (name, language, text). Short call-centre lines: what this model will say.
SENTENCES = [
    ("hi", "hi", "नमस्ते, मैं आपकी कैसे मदद कर सकती हूँ? आपका ऑर्डर कल तक पहुँच जाएगा।"),
    ("ta", "ta", "வணக்கம், உங்களுக்கு எப்படி உதவலாம்? உங்கள் ஆர்டர் நாளை வந்து சேரும்."),
    ("bn", "bn", "নমস্কার, আমি কীভাবে সাহায্য করতে পারি? আপনার অর্ডার কাল পৌঁছে যাবে।"),
    ("te", "te", "నమస్కారం, నేను మీకు ఎలా సహాయం చేయగలను? మీ ఆర్డర్ రేపు వస్తుంది."),
    ("mr", "mr", "नमस्कार, मी तुमची कशी मदत करू शकते? तुमची ऑर्डर उद्या पोहोचेल."),
    ("en", "en", "Hello, how can I help you today? Your order will arrive tomorrow."),
]
LONG = ("यह एक लंबा वाक्य है जिसे बीच में ही रोका जाएगा, ताकि हम देख सकें कि कॉल करने वाले के "
        "फ़ोन रखते ही सर्वर पर बनना बंद हो जाता है या नहीं। ") * 3


class Client:
    def __init__(self, url: str) -> None:
        u = urllib.parse.urlparse(url)
        self.host, self.port = u.hostname, u.port or 80

    def _conn(self, timeout=180):
        return http.client.HTTPConnection(self.host, self.port, timeout=timeout)

    def get(self, path: str):
        c = self._conn(10)
        try:
            c.request("GET", path)
            r = c.getresponse()
            return r.status, json.loads(r.read() or b"{}")
        finally:
            c.close()

    def speak(self, body: dict, stop_after_s: float | None = None) -> dict:
        """POST /v1/audio/speech and read it as a stream, timing the first byte."""
        c = self._conn()
        t0 = time.perf_counter()
        c.request("POST", "/v1/audio/speech", json.dumps(body).encode(),
                  {"Content-Type": "application/json"})
        r = c.getresponse()
        out = {"status": r.status, "headers": {k.lower(): v for k, v in r.getheaders()}}
        if r.status != 200:
            out["error"] = json.loads(r.read() or b"{}").get("error", {})
            c.close()
            return out
        chunks, ttfa = [], None
        while True:
            data = r.read1(65536) if hasattr(r, "read1") else r.read(4096)
            if not data:
                break
            if ttfa is None:
                ttfa = time.perf_counter() - t0
            chunks.append(data)
            if stop_after_s is not None and time.perf_counter() - t0 > stop_after_s:
                c.close()   # hang up: the adapter must abort the sidecar request
                out["hung_up"] = True
                break
        total = time.perf_counter() - t0
        c.close()
        body_bytes = b"".join(chunks)
        out.update(bytes=body_bytes, ttfa_s=ttfa, total_s=total)
        return out


def pcm_stats(res: dict) -> dict:
    audio_s = len(res.get("bytes", b"")) / 2 / RATE
    return {"ttfa_ms": None if res.get("ttfa_s") is None else round(res["ttfa_s"] * 1000),
            "audio_s": round(audio_s, 2), "total_s": round(res.get("total_s", 0), 2),
            "rtf": round(res["total_s"] / audio_s, 3) if audio_s else None}


def save_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


def gpu_mem(gpu: int | None) -> str | None:
    if gpu is None or not shutil.which("nvidia-smi"):
        return None
    out = subprocess.run(["nvidia-smi", "-i", str(gpu), "--query-gpu=memory.used,memory.total",
                          "--format=csv,noheader"], capture_output=True, text=True)
    return out.stdout.strip() or out.stderr.strip()


def sidecar_log(container: str, since: str) -> list[str]:
    if not shutil.which("docker"):
        return ["(docker not on PATH; check the sidecar log by hand)"]
    out = subprocess.run(["docker", "logs", "--since", since, container],
                         capture_output=True, text=True)
    text = (out.stdout + out.stderr).splitlines()
    return [ln for ln in text if any(k in ln.lower() for k in ("abort", "disconnect", "cancel"))]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", default="http://127.0.0.1:8202")
    ap.add_argument("--gpu", type=int, default=1, help="GPU index for nvidia-smi (-1 to skip)")
    ap.add_argument("--sidecar-container", default="voicera_higgs_test_sglang")
    ap.add_argument("--out", default="higgs-smoke-out")
    ap.add_argument("--wait-min", type=float, default=30, help="how long to wait for /health")
    args = ap.parse_args()
    gpu = None if args.gpu < 0 else args.gpu
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    cli = Client(args.url)
    report: dict = {"url": args.url, "started": time.strftime("%Y-%m-%d %H:%M:%S")}

    def say(*a):
        print(*a, flush=True)

    # 1. health ------------------------------------------------------------
    say(f"[1] waiting for {args.url}/health (up to {args.wait_min:.0f} min) ...")
    deadline, last = time.time() + args.wait_min * 60, None
    while True:
        try:
            status, health = cli.get("/health")
        except OSError as exc:
            status, health = 0, {"status": f"unreachable: {exc}"}
        if status == 200:
            break
        if health.get("status") != last:
            say(f"    {health.get('status')} (sidecar: {health.get('sidecar')})")
            last = health.get("status")
        if time.time() > deadline:
            say("    gave up. docker logs voicera_higgs_test_sglang --tail 100 says why.")
            report["health"] = health
            (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
            sys.exit(1)
        time.sleep(10)
    report["health"] = health
    say(f"    ready: voices with clips={health.get('voices')} zero_shot={health.get('zero_shot')}")
    voice = (health.get("voices") or ["default"])[0]
    report["voice"] = voice

    # 2. memory ------------------------------------------------------------
    report["gpu_mem_ready"] = gpu_mem(gpu)
    say(f"[2] GPU {gpu} memory used/total at ready: {report['gpu_mem_ready']}")

    # warm-up: the first request pays for graph capture and caches
    cli.speak({"input": "नमस्ते", "voice": voice, "response_format": "pcm"})

    # 3. languages ---------------------------------------------------------
    say("[3] languages (pcm, streamed)")
    report["languages"] = {}
    for name, _lang, text in SENTENCES:
        res = cli.speak({"input": text, "voice": voice, "response_format": "pcm"})
        if res["status"] != 200:
            report["languages"][name] = {"status": res["status"], "error": res.get("error")}
            say(f"    {name}: HTTP {res['status']} {res.get('error')}")
            continue
        save_wav(out / f"lang_{name}.wav", res["bytes"])
        st = pcm_stats(res)
        report["languages"][name] = st
        say(f"    {name}: ttfa {st['ttfa_ms']} ms, {st['audio_s']} s audio, rtf {st['rtf']}")

    # 4. contract ----------------------------------------------------------
    say("[4] contract")
    hi = SENTENCES[0][2]
    cases = {
        "emotion_elation": {"instructions": "emotion:elation"},
        "whispering": {"instructions": "style:whispering"},
        "speed_1.2": {"speed": 1.2},
        "speed_0.8": {"speed": 0.8},
        "inline_tags": {
            "input": "ठीक है <|prosody:pause|> एक मिनट रुकिए। <|sfx:laughter|>हाहा, हो गया।"},
    }
    report["contract"] = {}
    for name, extra in cases.items():
        body = {"input": hi, "voice": voice, "response_format": "pcm", **extra}
        res = cli.speak(body)
        row = {"status": res["status"], "speed_applied": res["headers"].get("x-speed-applied"),
               "tags": res["headers"].get("x-delivery-tags")}
        if res["status"] == 200:
            save_wav(out / f"contract_{name}.wav", res["bytes"])
            row.update(pcm_stats(res))
        else:
            row["error"] = res.get("error")
        report["contract"][name] = row
        say(f"    {name}: {row}")
    for fmt in ("wav", "mp3", "flac", "opus"):
        res = cli.speak({"input": hi, "voice": voice, "response_format": fmt})
        ok = res["status"] == 200 and res["headers"].get("x-audio-format") == fmt
        if ok:
            (out / f"format.{fmt}").write_bytes(res["bytes"])
        report["contract"][f"format_{fmt}"] = {"ok": ok, "status": res["status"],
                                               "bytes": len(res.get("bytes", b""))}
        say(f"    format {fmt}: {'ok' if ok else 'FAIL'} ({len(res.get('bytes', b''))} bytes)")
    sse = cli.speak({"input": hi, "voice": voice, "response_format": "pcm", "stream_format": "sse"})
    events = [json.loads(ln[6:]) for ln in sse.get("bytes", b"").decode().splitlines()
              if ln.startswith("data: ")]
    deltas = [e for e in events if e.get("type") == "speech.audio.delta"]
    done = events[-1] if events else {}
    if deltas:
        save_wav(out / "sse.wav", b"".join(base64.b64decode(e["audio"]) for e in deltas))
    report["contract"]["sse"] = {"deltas": len(deltas), "done": done.get("type"),
                                 "truncated": done.get("truncated"), "timings": done.get("timings")}
    say(f"    sse: {len(deltas)} deltas, last event {done.get('type')}")

    # 5. refusals ----------------------------------------------------------
    say("[5] refusals")
    refusals = {
        "free_text_instructions": {"instructions": "happy and fast"},
        "unknown_voice": {"voice": "Nobody"},
        "unknown_inline_tag": {"input": "hello <|sfx:applause|>"},
    }
    report["refusals"] = {}
    for name, extra in refusals.items():
        res = cli.speak({"input": hi, "voice": voice, "response_format": "pcm", **extra})
        report["refusals"][name] = {"status": res["status"],
                                    "param": (res.get("error") or {}).get("param")}
        say(f"    {name}: HTTP {res['status']} (expect 400)")

    # 6. concurrency -------------------------------------------------------
    say("[6] concurrency (same Hindi line, parallel)")
    report["concurrency"] = {}
    for n in (1, 4, 8):
        results: list[dict] = []

        def one(results=results):
            results.append(cli.speak({"input": hi, "voice": voice, "response_format": "pcm"}))

        threads = [threading.Thread(target=one) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        stats = [pcm_stats(r) for r in results if r["status"] == 200]
        ttfas = [s["ttfa_ms"] for s in stats if s["ttfa_ms"] is not None]
        rtfs = [s["rtf"] for s in stats if s["rtf"] is not None]
        row = {"ok": len(stats), "of": n,
               "ttfa_ms_median": statistics.median(ttfas) if ttfas else None,
               "ttfa_ms_max": max(ttfas) if ttfas else None,
               "rtf_median": round(statistics.median(rtfs), 3) if rtfs else None,
               "rtf_max": max(rtfs) if rtfs else None}
        report["concurrency"][str(n)] = row
        say(f"    x{n}: {row}")
    report["gpu_mem_after_load"] = gpu_mem(gpu)
    say(f"    GPU memory after load: {report['gpu_mem_after_load']}")

    # 7. barge-in ----------------------------------------------------------
    say("[7] hang-up mid-utterance")
    since = time.strftime("%Y-%m-%dT%H:%M:%S")
    res = cli.speak({"input": LONG, "voice": voice, "response_format": "pcm"}, stop_after_s=1.5)
    time.sleep(3)
    lines = sidecar_log(args.sidecar_container, since)
    after = cli.speak({"input": "ठीक है।", "voice": voice, "response_format": "pcm"})
    report["barge_in"] = {"hung_up": res.get("hung_up", False),
                          "sidecar_log_lines": lines[-5:],
                          "next_request_ttfa_ms": pcm_stats(after)["ttfa_ms"]}
    say(f"    hung up: {res.get('hung_up', False)}; sidecar abort/disconnect log lines: "
        f"{len(lines)}; next request ttfa {report['barge_in']['next_request_ttfa_ms']} ms")
    for ln in lines[-5:]:
        say(f"      {ln[:160]}")

    report["finished"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    say(f"\nDone. Listen to {out}/lang_*.wav and contract_*.wav; paste {out}/report.json back.")


if __name__ == "__main__":
    main()
