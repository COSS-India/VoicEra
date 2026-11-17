"""One timed synthesis, over any of the four paths the server offers.

The point of having all four in one place is that they measure different things
and a report that only covers one is misleading:

    ws        streaming, raw PCM frames. The lowest-latency path and the one a
              voice agent actually uses. The only path that reports the server's
              own view of the request, in the closing `done` frame.
    http      streaming, chunked HTTP (`response_format: pcm`). What an OpenAI
              client gets.
    sse       streaming, base64 in server-sent events. Same audio, more framing
              overhead - worth measuring rather than assuming it is free.

Buffered synthesis (response_format=wav and friends) is deliberately absent: this
deployment is for live streaming, so a complete-file path is out of scope. One
consequence to know when reading results - the server's own X-TTFA-Ms / X-RTF
headers only ever existed on that buffered path, because a streaming response
commits its headers before the audio exists. Server-side ground truth therefore
comes only from the WS `done` frame.

Timing rule that matters: a streaming response commits its headers before the
first audio byte (measured: ttfb 0.004 s on a 1.97 s request). So TTFA is timed
from the first NON-EMPTY body chunk, never from the response object.

Needs httpx and websockets; no numpy, so the per-request cost stays small enough
not to perturb what it is measuring.
"""

from __future__ import annotations

import array
import base64
import json
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx
import websockets

SAMPLE_RATE = 24000
BYTES_PER_SAMPLE = 2
# The reading speed the server's own duration guard assumes (engine.guard_chars_
# per_second). Used here only to recognise a runaway generation on the paths that
# cannot report finish_reason.
GUARD_CHARS_PER_SECOND = 8.0
RUNAWAY_FACTOR = 3.0


@dataclass
class Result:
    """One request. A failure is a result too - never raises."""

    protocol: str
    ok: bool = False
    error: Optional[str] = None
    ttfa_s: Optional[float] = None
    total_s: float = 0.0
    audio_s: float = 0.0
    n_chunks: int = 0
    gaps_s: list[float] = field(default_factory=list)
    # The server's own numbers, where the path can carry them.
    finish_reason: Optional[str] = None
    server_ttfa_ms: Optional[float] = None
    server_rtf: Optional[float] = None
    soft_eos_ignored: int = 0
    # Sanity, so a broken response cannot be counted as a fast one.
    silent: bool = False
    muted: bool = False

    @property
    def rtf(self) -> Optional[float]:
        return self.total_s / self.audio_s if self.audio_s else None


def _is_silent(pcm: bytes) -> bool:
    """All-zero audio is a failure that otherwise looks like a very fast success.

    Checks a sparse sample rather than every frame - enough to catch a dead
    stream without adding measurable cost to the request being timed.
    """
    if not pcm:
        return True
    a = array.array("h")
    a.frombytes(pcm[: len(pcm) - (len(pcm) % BYTES_PER_SAMPLE)])
    step = max(1, len(a) // 2000)
    return max((abs(x) for x in a[::step]), default=0) < 64


def _finish(r: Result, text: str, pcm: bytes, started: float) -> Result:
    r.total_s = time.monotonic() - started
    r.audio_s = len(pcm) / (SAMPLE_RATE * BYTES_PER_SAMPLE)
    if not pcm:
        r.error = r.error or "no audio returned"
        return r
    r.silent = _is_silent(pcm)
    # A runaway generation returns plenty of bytes, nearly all of them silence,
    # and would otherwise inflate audio-seconds-per-second throughput. Trust the
    # server's own word when the path carries it; fall back to the duration the
    # text should have taken.
    if r.finish_reason is not None:
        r.muted = r.finish_reason == "max_tokens"
    else:
        expected = len(text.strip()) / GUARD_CHARS_PER_SECOND
        r.muted = bool(expected and r.audio_s > RUNAWAY_FACTOR * expected)
    r.ok = not r.silent
    if r.silent:
        r.error = "audio is silent"
    return r


def _payload(voice: str, language: str, style: str, max_tokens: int) -> dict:
    """The fields shared by every path. The text field is named differently on the
    OpenAI route (`input`) and the native one (`text`), so callers add it."""
    body = {"voice": voice, "language": language}
    if style:
        body["style"] = style
    if max_tokens:
        body["max_tokens"] = max_tokens
    return body


async def synth_http(client: httpx.AsyncClient, base: str, text: str, *, voice: str,
                     language: str, style: str = "", max_tokens: int = 0,
                     fmt: str = "pcm") -> Result:
    """Streaming chunked HTTP, the OpenAI-compatible path."""
    r = Result("http")
    body = _payload(voice, language, style, max_tokens)
    body["input"] = text
    body["response_format"] = fmt
    pcm = bytearray()
    started = time.monotonic()
    last = started
    try:
        async with client.stream("POST", f"{base}/v1/audio/speech", json=body) as resp:
            if resp.status_code != 200:
                r.error = f"HTTP {resp.status_code}: {(await resp.aread())[:160].decode(errors='replace')}"
                return r
            async for chunk in resp.aiter_raw():
                if not chunk:
                    continue
                now = time.monotonic()
                if r.ttfa_s is None:
                    r.ttfa_s = now - started
                else:
                    r.gaps_s.append(now - last)
                last = now
                r.n_chunks += 1
                pcm += chunk
    except Exception as exc:                                     # noqa: BLE001
        r.error = f"{type(exc).__name__}: {exc}"
        return r
    return _finish(r, text, bytes(pcm), started)


async def synth_sse(client: httpx.AsyncClient, base: str, text: str, *, voice: str,
                    language: str, style: str = "", max_tokens: int = 0) -> Result:
    """Streaming server-sent events, base64 audio deltas."""
    r = Result("sse")
    body = _payload(voice, language, style, max_tokens)
    body["input"] = text
    body["response_format"] = "pcm"
    body["stream_format"] = "sse"
    pcm = bytearray()
    started = time.monotonic()
    last = started
    try:
        async with client.stream("POST", f"{base}/v1/audio/speech", json=body) as resp:
            if resp.status_code != 200:
                r.error = f"HTTP {resp.status_code}: {(await resp.aread())[:160].decode(errors='replace')}"
                return r
            async for line in resp.aiter_lines():
                if not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except ValueError:
                    continue
                if ev.get("type") == "speech.audio.delta":
                    now = time.monotonic()
                    if r.ttfa_s is None:
                        r.ttfa_s = now - started
                    else:
                        r.gaps_s.append(now - last)
                    last = now
                    r.n_chunks += 1
                    pcm += base64.b64decode(ev["audio"])
    except Exception as exc:                                     # noqa: BLE001
        r.error = f"{type(exc).__name__}: {exc}"
        return r
    return _finish(r, text, bytes(pcm), started)


async def synth_ws(ws_url: str, text: str, *, voice: str, language: str,
                   style: str = "", max_tokens: int = 0) -> Result:
    """Streaming WebSocket. The only path that reports the server's own metrics."""
    r = Result("ws")
    req = {"text": text, "voice": voice, "language": language}
    if style:
        req["style"] = style
    if max_tokens:
        req["max_tokens"] = max_tokens
    pcm = bytearray()
    started = time.monotonic()
    last = started
    try:
        async with websockets.connect(ws_url, max_size=None, open_timeout=15) as ws:
            await ws.send(json.dumps(req))
            async for msg in ws:
                if isinstance(msg, (bytes, bytearray)):
                    now = time.monotonic()
                    if r.ttfa_s is None:
                        r.ttfa_s = now - started
                    else:
                        r.gaps_s.append(now - last)
                    last = now
                    r.n_chunks += 1
                    pcm += msg
                    continue
                ev = json.loads(msg)
                if ev.get("type") == "done":
                    m = ev.get("metrics") or {}
                    r.finish_reason = m.get("finish_reason")
                    r.server_ttfa_ms = m.get("ttfa_ms")
                    r.server_rtf = m.get("rtf")
                    r.soft_eos_ignored = m.get("soft_eos_ignored") or 0
                    break
                if ev.get("type") == "error":
                    r.error = str(ev.get("message"))[:160]
                    return r
    except Exception as exc:                                     # noqa: BLE001
        r.error = f"{type(exc).__name__}: {exc}"
        return r
    return _finish(r, text, bytes(pcm), started)


SYNTH = {"ws": synth_ws, "http": synth_http, "sse": synth_sse}
