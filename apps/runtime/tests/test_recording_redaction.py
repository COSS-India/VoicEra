"""Tests for call recording redaction (VE-122, #243): switch, muting, carrier recordings."""

from __future__ import annotations

import io
import sys
import wave
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pipecat.frames.frames import (
    BotStartedSpeakingFrame,
    BotStoppedSpeakingFrame,
    TTSTextFrame,
)
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor
from pipecat.processors.frame_processor import FrameDirection

_mock_runners = MagicMock()
_mock_runners.run_telephony_bot = AsyncMock()
_mock_runners.run_websocket_bot = AsyncMock()
sys.modules.setdefault("apps.runtime.services.pipecat.runners", _mock_runners)

from apps.runtime.routes import provider_recording as provider_recording_route
from apps.runtime.routes import telephony as telephony_route
from apps.runtime.routes import vi_telephony
from apps.runtime.services.pipecat.events.recording import register_recording_handlers
from apps.runtime.services.privacy import audio
from apps.runtime.services.privacy.audio import (
    AgentSegment,
    TurnTiming,
    mute,
    plan_mutes,
    provider_recording_allowed,
    recording_enabled,
    timings_for_turns,
)
from apps.runtime.services.privacy.redaction import redact_turns_with_spans
from apps.runtime.services.storage import recording as recording_module
from apps.runtime.services.storage import transcript as transcript_module
from apps.runtime.services.storage.recording import (
    CallRecording,
    TimedAudioBufferProcessor,
)
from apps.runtime.services.storage.transcript import TranscriptWriter

RATE = 16000
T0 = 1_800_000_000.0  # recording start, epoch seconds


@pytest.fixture
def redaction_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PII_REDACTION_ENABLED", "true")
    monkeypatch.delenv("PII_REDACTION_ENTITIES", raising=False)
    monkeypatch.delenv("CALL_RECORDING_ENABLED", raising=False)


@pytest.fixture
def redaction_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PII_REDACTION_ENABLED", raising=False)
    monkeypatch.delenv("CALL_RECORDING_ENABLED", raising=False)


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat()


def _constant_track(seconds: float, value: int) -> bytes:
    return np.full(int(seconds * RATE), value, dtype="<i2").tobytes()


def _samples(track: bytes) -> np.ndarray:
    return np.frombuffer(track, dtype="<i2")


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, True), ("", True), ("true", True), ("1", True), ("false", False), ("0", False), ("off", False), (" No ", False)],
)
def test_recording_switch(monkeypatch: pytest.MonkeyPatch, value: str | None, expected: bool) -> None:
    if value is None:
        monkeypatch.delenv("CALL_RECORDING_ENABLED", raising=False)
    else:
        monkeypatch.setenv("CALL_RECORDING_ENABLED", value)
    assert recording_enabled() is expected


@pytest.mark.parametrize(
    ("recording", "redaction", "allowed"),
    [("true", "false", True), ("true", "true", False), ("false", "false", False), ("false", "true", False)],
)
def test_carrier_recording_allowed(
    monkeypatch: pytest.MonkeyPatch, recording: str, redaction: str, allowed: bool
) -> None:
    monkeypatch.setenv("CALL_RECORDING_ENABLED", recording)
    monkeypatch.setenv("PII_REDACTION_ENABLED", redaction)
    assert provider_recording_allowed() is allowed


# --------------------------------------------------------------------------- #
# Muting audio
# --------------------------------------------------------------------------- #


def test_mute_replaces_only_the_window_with_a_quiet_tone() -> None:
    track = _constant_track(3.0, 1000)
    muted = _samples(mute(track, RATE, [(1.0, 2.0)]))
    assert len(muted) == 3 * RATE
    assert (muted[: RATE - 1] == 1000).all()
    assert (muted[2 * RATE + 1 :] == 1000).all()
    window = muted[RATE : 2 * RATE]
    assert (window != 1000).mean() > 0.99
    assert np.abs(window).max() <= int(audio.TONE_LEVEL * 32767) + 1
    assert np.abs(window).max() > 0  # a tone, not silence


def test_mute_merges_overlaps_and_clamps_to_the_track() -> None:
    track = _constant_track(2.0, 500)
    muted = _samples(mute(track, RATE, [(-1.0, 0.5), (0.4, 0.8), (1.5, 9.0)]))
    assert len(muted) == 2 * RATE
    assert (muted[: int(0.8 * RATE)] != 500).mean() > 0.99
    assert (muted[int(0.8 * RATE) + 1 : int(1.5 * RATE) - 1] == 500).all()
    assert (muted[int(1.5 * RATE) :] != 500).mean() > 0.99


def test_mute_with_no_windows_returns_the_track_unchanged() -> None:
    track = _constant_track(1.0, 42)
    assert mute(track, RATE, []) == track


# --------------------------------------------------------------------------- #
# Planning what to mute
# --------------------------------------------------------------------------- #


def _turns(redaction_turns: list[tuple[str, float, float, str]]) -> list[TurnTiming]:
    redacted = redact_turns_with_spans([(role, content) for role, _, _, content in redaction_turns])
    return timings_for_turns(
        [(role, _iso(start), end, content) for role, start, end, content in redaction_turns], redacted
    )


def test_caller_utterance_with_pii_is_muted_with_padding(redaction_on: None) -> None:
    turns = _turns(
        [
            ("user", T0 + 1.0, T0 + 3.0, "hello, I want to check my ration card"),
            ("user", T0 + 10.0, T0 + 14.0, "my number is nine eight seven six five four three two one zero"),
        ]
    )
    user_windows, agent_windows = plan_mutes(turns, [], T0)
    assert agent_windows == []
    assert user_windows == [pytest.approx((10.0 - audio.USER_PAD_BEFORE, 14.0 + audio.USER_PAD_AFTER))]


def test_caller_utterance_with_digits_read_out_is_muted_even_if_the_transcript_kept_it(
    redaction_on: None,
) -> None:
    # Four digits read out: kept in the stored transcript, muted in the audio.
    turns = _turns([("user", T0 + 5.0, T0 + 7.0, "the last digits are nine eight seven six")])
    assert turns[0].spans
    user_windows, _ = plan_mutes(turns, [], T0)
    assert len(user_windows) == 1


def test_split_number_mutes_both_caller_utterances(redaction_on: None) -> None:
    turns = _turns(
        [
            ("user", T0 + 2.0, T0 + 4.0, "ninety eight"),
            ("user", T0 + 5.0, T0 + 8.0, "seventy six fifty four thirty two ten"),
        ]
    )
    user_windows, _ = plan_mutes(turns, [], T0)
    assert len(user_windows) == 2


def test_only_the_agent_sentence_with_pii_is_muted(redaction_on: None) -> None:
    content = "Thank you. Your number is 9876543210. Is that correct?"
    turns = _turns([("assistant", T0 + 20.0, T0 + 29.0, content)])
    segments = [
        AgentSegment(20.0, 21.0, "Thank you."),
        AgentSegment(21.0, 25.0, " Your number is 9876543210."),
        AgentSegment(25.0, 27.0, " Is that correct?"),
    ]
    _, agent_windows = plan_mutes(turns, segments, T0)
    assert agent_windows == [pytest.approx((21.0 - audio.AGENT_PAD, 25.0 + audio.AGENT_PAD))]


def test_agent_sentences_are_matched_across_turns_in_order(redaction_on: None) -> None:
    turns = _turns(
        [
            ("assistant", T0 + 1.0, T0 + 3.0, "Hello. Please tell me your number."),
            ("user", T0 + 4.0, T0 + 8.0, "nine eight seven six five four three two one zero"),
            ("assistant", T0 + 9.0, T0 + 14.0, "Hello. Your number is 9876543210."),
        ]
    )
    segments = [
        AgentSegment(1.0, 2.0, "Hello."),
        AgentSegment(2.0, 3.0, " Please tell me your number."),
        AgentSegment(9.0, 10.0, "Hello."),
        AgentSegment(10.0, 13.0, " Your number is 9876543210."),
    ]
    user_windows, agent_windows = plan_mutes(turns, segments, T0)
    assert len(user_windows) == 1
    assert agent_windows == [pytest.approx((10.0 - audio.AGENT_PAD, 13.0 + audio.AGENT_PAD))]


def test_cut_off_agent_audio_is_muted_when_its_turn_had_pii(redaction_on: None) -> None:
    turns = _turns([("assistant", T0 + 30.0, T0 + 34.0, "Your date of birth is 15 December 2021")])
    segments = [AgentSegment(30.0, 33.5, None)]
    _, agent_windows = plan_mutes(turns, segments, T0)
    assert len(agent_windows) == 1


def test_unmatched_agent_sentence_is_muted_if_it_contains_pii(redaction_on: None) -> None:
    segments = [AgentSegment(40.0, 43.0, "Your OTP is 4 5 6 7."), AgentSegment(43.0, 45.0, "Goodbye.")]
    _, agent_windows = plan_mutes([], segments, T0)
    assert len(agent_windows) == 1


def test_nothing_is_muted_in_a_call_without_pii(redaction_on: None) -> None:
    turns = _turns(
        [
            ("assistant", T0 + 1.0, T0 + 3.0, "Today's price is 2400 rupees."),
            ("user", T0 + 4.0, T0 + 6.0, "the rate was 2400 2500 2600"),
        ]
    )
    segments = [AgentSegment(1.0, 3.0, "Today's price is 2400 rupees.")]
    assert plan_mutes(turns, segments, T0) == ([], [])


# --------------------------------------------------------------------------- #
# Recorder subclass
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_recorder_notes_agent_sentence_timings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(AudioBufferProcessor, "process_frame", AsyncMock())
    clock = iter([T0 + 1.0, T0 + 3.0, T0 + 5.5, T0 + 7.0])
    monkeypatch.setattr(recording_module.time, "time", lambda: next(clock))
    recorder = TimedAudioBufferProcessor(sample_rate=RATE)
    recorder.recording_started_at = T0
    down = FrameDirection.DOWNSTREAM
    await recorder.process_frame(BotStartedSpeakingFrame(), down)
    await recorder.process_frame(TTSTextFrame("Hello there.", aggregated_by="sentence"), down)
    await recorder.process_frame(TTSTextFrame("Your number is 9876543210.", aggregated_by="sentence"), down)
    await recorder.process_frame(BotStoppedSpeakingFrame(), down)
    assert recorder.agent_segments == [
        AgentSegment(1.0, 3.0, "Hello there."),
        AgentSegment(3.0, 5.5, "Your number is 9876543210."),
        AgentSegment(5.5, 7.0, None),
    ]


@pytest.mark.asyncio
async def test_recorder_clock_starts_at_the_first_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    from pipecat.frames.frames import InputAudioRawFrame

    monkeypatch.setattr(AudioBufferProcessor, "process_frame", AsyncMock())
    monkeypatch.setattr(AudioBufferProcessor, "start_recording", AsyncMock())
    clock = iter([T0 + 0.4, T0 + 2.4])
    monkeypatch.setattr(recording_module.time, "time", lambda: next(clock))
    recorder = TimedAudioBufferProcessor(sample_rate=RATE)
    await recorder.start_recording()
    assert recorder.recording_started_at is None
    frame = InputAudioRawFrame(audio=b"\x00\x00" * 160, sample_rate=RATE, num_channels=1)
    await recorder.process_frame(frame, FrameDirection.DOWNSTREAM)
    assert recorder.recording_started_at == T0 + 0.4
    await recorder.process_frame(BotStartedSpeakingFrame(), FrameDirection.DOWNSTREAM)
    assert recorder._segment_start == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_recorder_ignores_frames_before_recording_starts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(AudioBufferProcessor, "process_frame", AsyncMock())
    recorder = TimedAudioBufferProcessor(sample_rate=RATE)
    await recorder.process_frame(TTSTextFrame("hi", aggregated_by="sentence"), FrameDirection.DOWNSTREAM)
    assert recorder.agent_segments == []


# --------------------------------------------------------------------------- #
# Call end: muting, mixing and upload
# --------------------------------------------------------------------------- #


def _wav_samples(data: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(data)) as wf:
        assert wf.getnchannels() == 1 and wf.getframerate() == RATE
        return np.frombuffer(wf.readframes(wf.getnframes()), dtype="<i2")


@pytest.mark.asyncio
async def test_call_recording_uploads_only_the_muted_mix(
    redaction_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload = AsyncMock(return_value=True)
    monkeypatch.setattr(recording_module, "save_and_link", upload)
    recorder = TimedAudioBufferProcessor(sample_rate=RATE)
    recorder.recording_started_at = T0
    recorder.agent_segments = [AgentSegment(6.0, 8.0, "Your number is 9876543210.")]
    recording = CallRecording(org_id="org-1", call_id="call-1", recorder=recorder)
    recording.hold(_constant_track(10.0, 1000), _constant_track(10.0, 2000), RATE)
    turns = _turns(
        [
            ("user", T0 + 2.0, T0 + 4.0, "nine eight seven six five four three two one zero"),
            ("assistant", T0 + 6.0, T0 + 8.5, "Your number is 9876543210."),
        ]
    )
    await recording.flush(turns)

    kwargs = upload.await_args.kwargs
    assert kwargs["filename"] == "recording.wav" and kwargs["url_field"] == "recording_url"
    mixed = _wav_samples(kwargs["data"])
    assert len(mixed) == 10 * RATE
    assert (mixed[: int(1.4 * RATE)] == 3000).all()  # both voices, untouched
    caller = mixed[int(1.6 * RATE) : int(4.2 * RATE)]
    assert (caller != 3000).mean() > 0.99  # caller replaced by the tone ...
    assert abs(caller.mean() - 2000) < 50  # ... while the agent's audio stays
    agent = mixed[int(5.9 * RATE) : int(8.1 * RATE)]
    assert (agent != 3000).mean() > 0.99
    assert abs(agent.mean() - 1000) < 50  # caller kept, agent toned
    assert (mixed[int(9.0 * RATE) :] == 3000).all()
    assert recording._tracks is None  # raw audio dropped


@pytest.mark.asyncio
async def test_call_recording_is_not_stored_if_muting_fails(
    redaction_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload = AsyncMock(return_value=True)
    monkeypatch.setattr(recording_module, "save_and_link", upload)
    monkeypatch.setattr(recording_module, "plan_mutes", MagicMock(side_effect=RuntimeError("boom")))
    recorder = TimedAudioBufferProcessor(sample_rate=RATE)
    recording = CallRecording(org_id="org-1", call_id="call-1", recorder=recorder)
    recording.hold(_constant_track(1.0, 1), _constant_track(1.0, 1), RATE)
    await recording.flush([])
    upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_call_recording_without_audio_uploads_nothing(
    redaction_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    upload = AsyncMock(return_value=True)
    monkeypatch.setattr(recording_module, "save_and_link", upload)
    monkeypatch.setattr(recording_module, "_TRACKS_TIMEOUT_SECS", 0.01)
    recording = CallRecording(org_id="org-1", call_id="call-1", recorder=TimedAudioBufferProcessor(sample_rate=RATE))
    await recording.flush([])
    upload.assert_not_awaited()


@pytest.mark.asyncio
async def test_transcript_flush_provides_turn_timings(
    redaction_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(transcript_module, "save_and_link", AsyncMock(return_value=True))
    writer = TranscriptWriter(org_id="org-1", call_id="call-1")
    writer.append("assistant", _iso(T0 + 1.0), "Please tell me your number.")
    writer.append("user", _iso(T0 + 3.0), "nine eight seven six five four three two one zero")
    await writer.flush()
    roles = [(t.role, t.has_pii) for t in writer.turn_timings]
    assert roles == [("assistant", False), ("user", True)]
    assert writer.turn_timings[1].start == pytest.approx(T0 + 3.0)


@pytest.mark.asyncio
async def test_transcript_has_no_turn_timings_when_redaction_is_off(
    redaction_off: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(transcript_module, "save_and_link", AsyncMock(return_value=True))
    writer = TranscriptWriter(org_id="org-1", call_id="call-1")
    writer.append("user", _iso(T0), "my number is 9876543210")
    await writer.flush()
    assert writer.turn_timings == []


# --------------------------------------------------------------------------- #
# Handler registration
# --------------------------------------------------------------------------- #


def _handlers(recorder: TimedAudioBufferProcessor, event: str) -> list:
    return list(recorder._event_handlers[event].handlers)


def test_recording_off_registers_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CALL_RECORDING_ENABLED", "false")
    recorder = TimedAudioBufferProcessor(sample_rate=RATE)
    assert register_recording_handlers(recorder, org_id="org-1", call_id="call-1") is None
    assert _handlers(recorder, "on_audio_data") == [] and _handlers(recorder, "on_track_audio_data") == []


def test_redaction_off_keeps_the_immediate_upload(redaction_off: None) -> None:
    recorder = TimedAudioBufferProcessor(sample_rate=RATE)
    assert register_recording_handlers(recorder, org_id="org-1", call_id="call-1") is None
    assert len(_handlers(recorder, "on_audio_data")) == 1
    assert _handlers(recorder, "on_track_audio_data") == []


def test_redaction_on_holds_the_tracks_for_muting(redaction_on: None) -> None:
    recorder = TimedAudioBufferProcessor(sample_rate=RATE)
    recording = register_recording_handlers(recorder, org_id="org-1", call_id="call-1")
    assert isinstance(recording, CallRecording)
    assert _handlers(recorder, "on_audio_data") == []
    assert len(_handlers(recorder, "on_track_audio_data")) == 1


def test_factory_follows_the_recording_switch() -> None:
    import inspect

    from apps.runtime.services.pipecat.factory import build_pipeline_components

    compact = "".join(inspect.getsource(build_pipeline_components).split())
    assert "audiobuffer=TimedAudioBufferProcessor(" in compact
    assert "auto_start_recording=recording_enabled()" in compact


# --------------------------------------------------------------------------- #
# Carrier recordings
# --------------------------------------------------------------------------- #


def _vi_client() -> TestClient:
    app = FastAPI()
    app.include_router(vi_telephony.router)
    return TestClient(app)


def test_carrier_recording_is_not_stored_with_redaction_on(redaction_on: None) -> None:
    download = AsyncMock(return_value=b"RIFFDATA")
    save = AsyncMock(return_value=True)
    with (
        patch.object(provider_recording_route, "download_recording_url", new=download),
        patch.object(provider_recording_route, "save_and_link", new=save),
    ):
        response = _vi_client().post(
            "/vi/recording-webhook", json={"recording_url": "https://cdn.example/r.wav?callid=sid-1"}
        )
    assert response.status_code == 200
    assert response.json() == {"stored": False, "reason": "recording disabled"}
    download.assert_not_awaited()
    save.assert_not_awaited()


def test_carrier_recording_is_not_stored_with_recording_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CALL_RECORDING_ENABLED", "false")
    monkeypatch.delenv("PII_REDACTION_ENABLED", raising=False)
    save = AsyncMock(return_value=True)
    with patch.object(provider_recording_route, "save_and_link", new=save):
        response = _vi_client().post(
            "/vi/recording-webhook", json={"recording_url": "https://cdn.example/r.wav?callid=sid-1"}
        )
    assert response.status_code == 200
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_carrier_recording_is_not_started_with_redaction_on(redaction_on: None) -> None:
    auth = AsyncMock(return_value={})
    with patch.object(telephony_route.backend_client, "get_provider_auth", new=auth):
        await telephony_route._start_provider_recording("org-1", "plivo", "sid-1")
    auth.assert_not_awaited()


@pytest.mark.asyncio
async def test_carrier_recording_is_started_when_allowed(redaction_off: None) -> None:
    starter = AsyncMock()
    client = MagicMock(start_provider_recording=starter)
    with (
        patch.object(telephony_route.backend_client, "get_provider_auth", new=AsyncMock(return_value={})),
        patch.object(telephony_route, "build_config", new=MagicMock()),
        patch.object(telephony_route, "create_client", new=MagicMock(return_value=client)),
    ):
        await telephony_route._start_provider_recording("org-1", "plivo", "sid-1")
    starter.assert_awaited_once_with("sid-1")
