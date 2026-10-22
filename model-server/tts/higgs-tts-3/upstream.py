"""The SGLang-Omni sidecar, as this adapter sees it.

The sidecar serves Higgs TTS 3 on its own OpenAI-shaped `/v1/audio/speech`.
With `stream: true, response_format: pcm` it answers `audio/pcm` -- 24 kHz mono
signed 16-bit -- and names the rate in `X-Sample-Rate`. It sends its status line
only once the first audio chunk exists, so a refusal arrives as an ordinary
4xx/5xx with an OpenAI error body, never as a 200 that goes quiet.

**Cancellation is a closed connection.** SGLang-Omni watches each streaming
request for a client disconnect and aborts it in the engine
(`speech_audio_response` -> `abort_and_close_speech_stream`, checked against
sglang-omni 0.1.9). So when the caller hangs up, Starlette closes our body
iterator, `PcmStream.chunks()`'s `finally` closes the httpx response, the
sidecar sees the disconnect, and the GPU stops working on a sentence nobody is
listening to. Nothing here polls.

**Samples are kept whole.** HTTP chunk boundaries fall wherever they fall, and a
signed 16-bit sample split across two of them is two corrupt samples to any
encoder that reads chunks as arrays (mp3 here). `chunks()` re-aligns to 2 bytes
and carries the odd byte over.
"""
from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx

log = logging.getLogger("higgs.upstream")

#: The sidecar's status values for /health; only "healthy" answers 200.
_HEALTHY = "healthy"


class SidecarError(Exception):
    """The sidecar refused or could not be reached. Carries an HTTP status for the caller."""

    def __init__(self, status: int, message: str, param: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.param = param


@dataclass
class StreamStats:
    """One request's own timings -- never another concurrent stream's."""

    started: float = field(default_factory=time.perf_counter)
    first_audio: float | None = None
    finished: float | None = None
    pcm_bytes: int = 0
    sample_rate: int = 24000
    finish_reason: str | None = None

    @property
    def audio_ms(self) -> float:
        return self.pcm_bytes / 2 / self.sample_rate * 1000.0

    @property
    def gen_ms(self) -> float:
        end = self.finished or time.perf_counter()
        return (end - self.started) * 1000.0

    @property
    def ttfa_ms(self) -> float | None:
        return None if self.first_audio is None else (self.first_audio - self.started) * 1000.0

    @property
    def rtf(self) -> float | None:
        return None if self.audio_ms <= 0 else self.gen_ms / self.audio_ms

    @property
    def truncated(self) -> bool:
        # "length" is the sidecar's word for hitting max_new_tokens mid-utterance.
        return self.finish_reason == "length"

    def summary(self) -> dict:
        return {
            "ttfa_ms": None if self.ttfa_ms is None else round(self.ttfa_ms, 1),
            "generation_ms": round(self.gen_ms, 1),
            "audio_ms": round(self.audio_ms, 1),
            "rtf": None if self.rtf is None else round(self.rtf, 3),
            "finish_reason": self.finish_reason,
        }


class PcmStream:
    """An open streaming response from the sidecar."""

    def __init__(self, client: SidecarClient, response: httpx.Response, stats: StreamStats) -> None:
        self._client = client
        self._response = response
        self.stats = stats
        self.sample_rate = stats.sample_rate
        self.speech_id = response.headers.get("x-sglang-omni-speech-id")

    async def aclose(self) -> None:
        """Close the sidecar connection, which aborts generation there. Idempotent."""
        if self.stats.finished is None:
            self.stats.finished = time.perf_counter()
        await self._response.aclose()

    async def chunks(self) -> AsyncIterator[bytes]:
        """PCM in whole samples. Closing this generator aborts the sidecar request."""
        carry = b""
        completed = False
        try:
            async for chunk in self._response.aiter_bytes():
                if not chunk:
                    continue
                data = carry + chunk
                cut = len(data) - (len(data) % 2)
                carry = data[cut:]
                if cut:
                    if self.stats.first_audio is None:
                        self.stats.first_audio = time.perf_counter()
                    self.stats.pcm_bytes += cut
                    yield data[:cut]
            completed = True
        except httpx.HTTPError as exc:
            raise SidecarError(502, f"the sidecar stream broke mid-utterance: {exc}") from exc
        finally:
            await self.aclose()
            if carry:
                log.warning("sidecar stream ended on half a sample; dropped 1 byte")
        if completed:
            self.stats.finish_reason = await self._client.finish_reason(self.speech_id)


class SidecarClient:
    def __init__(self, base_url: str, timeout_s: float) -> None:
        self.base_url = base_url
        # read= is the wait between bytes, and the first byte is the first
        # audio chunk, so it has to cover time-to-first-audio under load.
        self._http = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(connect=5.0, read=timeout_s, write=10.0, pool=5.0),
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def health(self) -> tuple[bool, str]:
        """(ready, status). Never raises: an unreachable sidecar is simply not ready."""
        try:
            resp = await self._http.get("/health", timeout=3.0)
        except httpx.HTTPError as exc:
            return False, f"unreachable ({type(exc).__name__})"
        try:
            status = resp.json().get("status", "unknown")
        except ValueError:
            status = "unknown"
        return resp.status_code == 200 and status == _HEALTHY, status

    async def open_stream(self, payload: dict) -> PcmStream:
        """POST a streaming speech request; returns once the first audio exists."""
        stats = StreamStats()
        request = self._http.build_request("POST", "/v1/audio/speech", json=payload)
        try:
            response = await self._http.send(request, stream=True)
        except httpx.TimeoutException as exc:
            raise SidecarError(504, "the sidecar produced no audio in time") from exc
        except httpx.HTTPError as exc:
            raise SidecarError(503, f"the sidecar is unreachable: {exc}") from exc

        if response.status_code != 200:
            body = await response.aread()
            await response.aclose()
            raise _refusal(response.status_code, body)

        try:
            stats.sample_rate = int(response.headers.get("x-sample-rate", "24000"))
        except ValueError:
            await response.aclose()
            raise SidecarError(502, "the sidecar sent an unreadable X-Sample-Rate") from None
        return PcmStream(self, response, stats)

    async def finish_reason(self, speech_id: str | None) -> str | None:
        """Why a finished stream stopped. Best effort: the body carries no terminal event.

        SGLang-Omni records each finished stream's outcome under its speech id;
        "length" means max_new_tokens cut the utterance off.
        """
        if not speech_id:
            return None
        try:
            resp = await self._http.get(f"/v1/audio/speech/{speech_id}", timeout=2.0)
            if resp.status_code == 200:
                return resp.json().get("finish_reason")
        except (httpx.HTTPError, ValueError):
            pass
        return None


def _refusal(status: int, body: bytes) -> SidecarError:
    """Turn a sidecar error response into ours, keeping its message."""
    message, param = body.decode("utf-8", "replace")[:500], None
    try:
        import json

        err = json.loads(body).get("error") or {}
        message = err.get("message") or message
        param = err.get("param")
    except (ValueError, AttributeError):
        pass
    # Every field the sidecar validates was validated here first, so a 4xx from
    # it is most likely a reference clip it could not read -- still the
    # request's fault, still a 400. A 5xx is the sidecar's, so the caller sees a
    # bad gateway, not a bad request.
    if 400 <= status < 500:
        return SidecarError(400, f"the model refused the request: {message}", param)
    return SidecarError(502, f"the model failed: {message}")
