"""STT adapters mark the transcript that answers a VAD-stop flush as finalized.

Pipecat's turn-stop strategy releases the user turn as soon as a finalized
transcript arrives; otherwise it waits out the STT's P99 latency budget
(1.0s by default) even when the transcript is already in.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, patch

from pipecat.frames.frames import TranscriptionFrame
from pipecat.processors.frame_processor import FrameProcessor

from apps.providers.adapters.bhashini import asr_pb2
from apps.providers.adapters.bhashini.nemotron_stt import BhashiniNemotronSTTService
from apps.providers.local.indic_nemotron.stt import IndicNemotronSTTService


def _run(coro):
    return asyncio.run(coro)


def _silence_metrics(stt: Any) -> None:
    for name in (
        "start_processing_metrics",
        "stop_processing_metrics",
        "stop_ttfb_metrics",
    ):
        setattr(stt, name, AsyncMock())


async def _final_transcripts(stt: Any, drive) -> list[tuple[str, bool]]:
    """Run ``drive()`` and return (text, finalized) for pushed transcripts."""
    pushed: list[Any] = []

    async def record(_self, frame, direction=None) -> None:
        pushed.append(frame)

    with patch.object(FrameProcessor, "push_frame", record):
        await drive()
    return [(f.text, f.finalized) for f in pushed if isinstance(f, TranscriptionFrame)]


class _Inbox:
    """Async-iterable message source standing in for a websocket/gRPC stream."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.queue.get()


async def _with_receiver(receiver, steps) -> None:
    task = asyncio.create_task(receiver)
    try:
        await steps()
        await asyncio.sleep(0)  # let the receiver push what it already got
    finally:
        task.cancel()


def test_indic_nemotron_flush_answer_is_finalized() -> None:
    class FakeWebSocket(_Inbox):
        async def send(self, raw: str) -> None:
            if json.loads(raw).get("action") == "flush_eos":
                await self.queue.put(json.dumps({"text": "namaste", "is_final": True}))

    async def scenario():
        stt = IndicNemotronSTTService(ws_url="ws://test")
        _silence_metrics(stt)
        ws = stt._websocket = FakeWebSocket()

        async def steps():
            # A final the server sends on its own is not the flush answer.
            await ws.queue.put(json.dumps({"text": "haan", "is_final": True}))
            await asyncio.sleep(0)
            await stt._flush_utterance()

        return await _final_transcripts(
            stt, lambda: _with_receiver(stt._receive_handler(), steps)
        )

    assert _run(scenario()) == [("haan", False), ("namaste", True)]


def test_bhashini_nemotron_commit_answer_is_finalized() -> None:
    def final(text: str) -> asr_pb2.StreamingResponse:
        return asr_pb2.StreamingResponse(
            transcript=asr_pb2.Transcript(text=text, is_final=True)
        )

    async def scenario():
        stt = BhashiniNemotronSTTService(auth_token="token", function_id="fn")
        _silence_metrics(stt)
        call = _Inbox()
        stt._channel = object()
        stt._outbound = asyncio.Queue()

        async def answer_commit():
            await stt._outbound.get()
            await call.queue.put(final("namaste"))

        async def steps():
            await call.queue.put(final("haan"))
            await asyncio.sleep(0)
            answering = asyncio.create_task(answer_commit())
            await stt._flush_utterance()
            await answering

        try:
            return await _final_transcripts(
                stt, lambda: _with_receiver(stt._receive_handler(call), steps)
            )
        finally:
            stt._closed = True  # skip the receiver's reconnect cleanup

    assert _run(scenario()) == [("haan", False), ("namaste", True)]
