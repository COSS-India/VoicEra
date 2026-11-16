"""Unit tests for LLM hold message handling."""

from __future__ import annotations

import asyncio
import io
import wave
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pipecat.frames.frames import OutputAudioRawFrame, TTSSpeakFrame

from apps.runtime.services.pipecat.hold import HoldMessageHandler, hold_from_behaviour
from apps.runtime.services.pipecat.hold.audio_loader import decode_hold_pcm
from apps.runtime.services.pipecat.hold.clips import AudioHoldClip, TextHoldClip
from apps.runtime.services.pipecat.hold.players import AudioHoldPlayer, TextHoldPlayer

_MP3_PATH = Path(__file__).resolve().parent / "fixtures" / "hold_test.mp3"


class _MockTts:
    def __init__(self) -> None:
        self.queue_frame = AsyncMock()


def _text_handler(
    messages: list[str],
    *,
    timeout_seconds: float,
    tts: _MockTts,
) -> HoldMessageHandler:
    return HoldMessageHandler(
        clips=tuple(TextHoldClip(text=m) for m in messages),
        timeout_seconds=timeout_seconds,
        player=TextHoldPlayer(tts),
        mode="text",
    )


def _wav_bytes(*, sample_rate: int = 8000, frames: int = 160) -> bytes:
    pcm = b"\x00\x00" * frames
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


@pytest.mark.parametrize(
    "behaviour",
    [
        {},
        {"hold_messages": [], "hold_message_timeout_seconds": 0.6},
        {"hold_messages": ["Wait"], "hold_message_timeout_seconds": None},
        {"hold_messages": ["Wait"], "hold_message_timeout_seconds": 0},
        {
            "hold_mode": "audio",
            "hold_audio_clips": [],
            "hold_message_timeout_seconds": 0.6,
        },
    ],
)
def test_hold_from_behaviour_disabled(behaviour: dict[str, Any]) -> None:
    assert hold_from_behaviour(behaviour, _MockTts()) is None


def test_hold_from_behaviour_enabled() -> None:
    handler = hold_from_behaviour(
        {
            "hold_messages": ["One moment please.", "  "],
            "hold_message_timeout_seconds": 0.6,
        },
        _MockTts(),
    )
    assert handler is not None
    assert handler._messages == ["One moment please."]
    assert handler._timeout_seconds == 0.6


def test_hold_from_behaviour_audio_mode() -> None:
    handler = hold_from_behaviour(
        {
            "hold_mode": "audio",
            "hold_messages": ["ignored"],
            "hold_audio_clips": [
                {
                    "clip_id": "c1",
                    "storage_key": "hold-audio/org-1/c1/a.wav",
                    "filename": "a.wav",
                }
            ],
            "hold_message_timeout_seconds": 0.6,
        },
        _MockTts(),
        org_id="org-1",
        sample_rate=8000,
    )
    assert handler is not None
    assert handler._mode == "audio"
    assert len(handler._clips) == 1


@pytest.mark.asyncio
async def test_hold_plays_after_timeout() -> None:
    tts = _MockTts()
    handler = _text_handler(
        ["One moment please."],
        timeout_seconds=0.05,
        tts=tts,
    )
    clip = TextHoldClip(text="One moment please.")

    with patch(
        "apps.runtime.services.pipecat.hold.handler.random.choice",
        return_value=clip,
    ):
        await handler.on_inference_started()
        await asyncio.sleep(0.1)

    tts.queue_frame.assert_awaited_once()
    frame = tts.queue_frame.await_args.args[0]
    assert isinstance(frame, TTSSpeakFrame)
    assert frame.text == "One moment please."
    assert frame.append_to_context is False


@pytest.mark.asyncio
async def test_hold_cancelled_on_response() -> None:
    """Simulates first LLM TextFrame arriving after timer started but before timeout."""
    tts = _MockTts()
    handler = _text_handler(
        ["One moment please."],
        timeout_seconds=0.2,
        tts=tts,
    )

    await handler.on_inference_started()
    await asyncio.sleep(0.05)
    await handler.cancel()
    await asyncio.sleep(0.2)

    tts.queue_frame.assert_not_awaited()


@pytest.mark.asyncio
async def test_hold_cancelled_before_timeout() -> None:
    tts = _MockTts()
    handler = _text_handler(
        ["One moment please."],
        timeout_seconds=0.2,
        tts=tts,
    )

    await handler.on_inference_started()
    await handler.cancel()
    await asyncio.sleep(0.25)

    tts.queue_frame.assert_not_awaited()


@pytest.mark.asyncio
async def test_hold_plays_only_once_per_inference() -> None:
    tts = _MockTts()
    handler = _text_handler(["Hold on."], timeout_seconds=0.05, tts=tts)
    clip = TextHoldClip(text="Hold on.")

    with patch(
        "apps.runtime.services.pipecat.hold.handler.random.choice",
        return_value=clip,
    ):
        await handler.on_inference_started()
        await asyncio.sleep(0.1)
        await asyncio.sleep(0.1)

    assert tts.queue_frame.await_count == 1


@pytest.mark.asyncio
async def test_hold_uses_random_choice() -> None:
    tts = _MockTts()
    clips = (TextHoldClip(text="First"), TextHoldClip(text="Second"))
    handler = HoldMessageHandler(
        clips=clips,
        timeout_seconds=0.05,
        player=TextHoldPlayer(tts),
        mode="text",
    )

    with patch(
        "apps.runtime.services.pipecat.hold.handler.random.choice",
        return_value=clips[1],
    ) as mock_choice:
        await handler.on_inference_started()
        await asyncio.sleep(0.1)

    mock_choice.assert_called_once_with(clips)
    frame = tts.queue_frame.await_args.args[0]
    assert isinstance(frame, TTSSpeakFrame)
    assert frame.text == "Second"


@pytest.mark.asyncio
async def test_audio_hold_queues_output_frames() -> None:
    tts = _MockTts()
    pcm = b"\x01\x00" * 40  # 40 mono samples @ 8 kHz ≈ 5 ms; player still chunks
    clip = AudioHoldClip(
        clip_id="c1",
        storage_key="hold-audio/org-1/c1/a.wav",
        filename="a.wav",
        pcm=pcm,
        sample_rate=8000,
    )
    handler = HoldMessageHandler(
        clips=(clip,),
        timeout_seconds=0.05,
        player=AudioHoldPlayer(tts),
        mode="audio",
        org_id="org-1",
        sample_rate=8000,
    )

    with patch(
        "apps.runtime.services.pipecat.hold.handler.random.choice",
        return_value=clip,
    ):
        await handler.on_inference_started()
        await asyncio.sleep(0.1)

    assert tts.queue_frame.await_count >= 1
    frame = tts.queue_frame.await_args_list[0].args[0]
    assert isinstance(frame, OutputAudioRawFrame)
    assert frame.sample_rate == 8000
    assert frame.num_channels == 1


@pytest.mark.asyncio
async def test_prepare_drops_invalid_audio_clips() -> None:
    tts = _MockTts()
    clip = AudioHoldClip(
        clip_id="c1",
        storage_key="hold-audio/other-org/c1/a.wav",
        filename="a.wav",
    )
    handler = HoldMessageHandler(
        clips=(clip,),
        timeout_seconds=0.5,
        player=AudioHoldPlayer(tts),
        mode="audio",
        org_id="org-1",
        sample_rate=8000,
        fetch_bytes=AsyncMock(return_value=_wav_bytes()),
    )
    await handler.prepare()
    assert not handler.is_active
    assert handler._clips == ()


@pytest.mark.asyncio
async def test_prepare_loads_valid_audio_clip() -> None:
    tts = _MockTts()
    clip = AudioHoldClip(
        clip_id="c1",
        storage_key="hold-audio/org-1/c1/a.wav",
        filename="a.wav",
    )
    fetch = AsyncMock(return_value=_wav_bytes(sample_rate=8000, frames=160))
    handler = HoldMessageHandler(
        clips=(clip,),
        timeout_seconds=0.5,
        player=AudioHoldPlayer(tts),
        mode="audio",
        org_id="org-1",
        sample_rate=8000,
        fetch_bytes=fetch,
    )
    await handler.prepare()
    assert handler.is_active
    assert len(handler._clips) == 1
    loaded = handler._clips[0]
    assert isinstance(loaded, AudioHoldClip)
    assert loaded.pcm
    assert loaded.sample_rate == 8000
    fetch.assert_awaited_once_with("hold-audio/org-1/c1/a.wav")


def test_decode_hold_pcm_mp3() -> None:
    pcm, rate = decode_hold_pcm(
        _MP3_PATH.read_bytes(),
        filename="hold.mp3",
        target_rate=8000,
    )
    assert rate == 8000
    assert len(pcm) > 0
    assert len(pcm) % 2 == 0


@pytest.mark.asyncio
async def test_prepare_loads_mp3_clip() -> None:
    tts = _MockTts()
    clip = AudioHoldClip(
        clip_id="c1",
        storage_key="hold-audio/org-1/c1/a.mp3",
        filename="a.mp3",
    )
    fetch = AsyncMock(return_value=_MP3_PATH.read_bytes())
    handler = HoldMessageHandler(
        clips=(clip,),
        timeout_seconds=0.5,
        player=AudioHoldPlayer(tts),
        mode="audio",
        org_id="org-1",
        sample_rate=8000,
        fetch_bytes=fetch,
    )
    await handler.prepare()
    assert handler.is_active
    loaded = handler._clips[0]
    assert isinstance(loaded, AudioHoldClip)
    assert loaded.pcm
    assert loaded.sample_rate == 8000
