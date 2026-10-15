"""Shared harness for preview adapter contract tests (no pytest-asyncio or respx here)."""

from __future__ import annotations

import asyncio
import json
import wave
from io import BytesIO

import httpx

from apps.providers.preview import PreviewFn

FAKE_WAV = b"RIFF\x24\x00\x00\x00WAVEfmt "


def run_adapter(
    synthesize: PreviewFn, cfg, response: httpx.Response, text: str = "hi"
) -> tuple[bytes, httpx.Request]:
    """Run ``synthesize`` against a mock transport returning ``response``; return audio and the request sent."""
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return response

    async def run() -> bytes:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await synthesize(cfg, text, client)

    audio = asyncio.run(run())
    return audio, sent[0]


def json_body(request: httpx.Request) -> dict:
    """Decode the JSON body of a captured request."""
    return json.loads(request.content)


def wav_sample_rate(audio: bytes) -> int:
    """Return the frame rate written in a WAV header."""
    with wave.open(BytesIO(audio), "rb") as wf:
        return wf.getframerate()
