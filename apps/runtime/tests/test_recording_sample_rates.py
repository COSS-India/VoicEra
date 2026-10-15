"""Regression: Pipecat AudioBuffer recording duration/speed across TTS rates.

Covers the VI path where wire is 8 kHz, pipeline may be 8/16 kHz, and TTS may
be 8/16/24 kHz. Recording must use the pipeline rate after transport.output()
(stock Pipecat 1.8 pattern) so WAV duration matches wall-clock and bot audio
is not sped up.
"""

from __future__ import annotations

import inspect
import io
import wave
from types import SimpleNamespace

import pytest
from pipecat.frames.frames import InputAudioRawFrame, OutputAudioRawFrame
from pipecat.processors.audio.audio_buffer_processor import AudioBufferProcessor

from apps.runtime.services.pipecat.audio import wav_bytes
from apps.runtime.services.pipecat.factory import build_pipeline_components
from apps.telephony.providers.vi.rates import pipeline_sample_rate, resolve_vi_pipeline_rates
from apps.telephony.rates import PipelineRates


def _pcm_silence(sample_rate: int, seconds: float) -> bytes:
    return b"\x00\x00" * int(sample_rate * seconds)


def _wav_duration_seconds(wav: bytes) -> tuple[float, int]:
    with wave.open(io.BytesIO(wav), "rb") as wf:
        rate = wf.getframerate()
        frames = wf.getnframes()
        return frames / float(rate), rate


def _prime_buffer(buf: AudioBufferProcessor, sample_rate: int) -> None:
    """Enable recording without PipelineWorker TaskManager / event tasks."""
    buf._sample_rate = sample_rate
    buf._audio_buffer_size_1s = sample_rate * 2
    buf._recording = True
    buf._user_audio_buffer = bytearray()
    buf._bot_audio_buffer = bytearray()
    buf._last_user_buffer_update_time = None
    buf._last_bot_buffer_update_time = None


def test_wav_bytes_uses_reported_sample_rate_not_wire_rate() -> None:
    """WAV header must match Pipecat's on_audio_data sample_rate (e.g. 16k), not 8k wire."""
    pcm = _pcm_silence(16000, 1.0)
    wav = wav_bytes(pcm, 16000, 1)
    duration, rate = _wav_duration_seconds(wav)
    assert rate == 16000
    assert duration == pytest.approx(1.0, abs=0.01)


@pytest.mark.parametrize(
    ("tts_rate", "expected_pipeline"),
    [
        (8000, 8000),
        (16000, 16000),
        (24000, 16000),
    ],
)
def test_vi_pipeline_rate_for_tts_native_rates(tts_rate: int, expected_pipeline: int) -> None:
    tts = SimpleNamespace(_init_sample_rate=tts_rate, sample_rate=tts_rate)
    assert pipeline_sample_rate(tts, wire_rate=8000) == expected_pipeline
    rates = resolve_vi_pipeline_rates(tts)
    assert rates == PipelineRates(wire_rate=8000, pipeline_rate=expected_pipeline)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("pipeline_rate", "tts_frame_rate", "seconds"),
    [
        (8000, 8000, 0.5),
        (16000, 16000, 0.5),
        (16000, 24000, 0.5),
    ],
)
async def test_audiobuffer_duration_matches_wall_clock_across_tts_rates(
    pipeline_rate: int,
    tts_frame_rate: int,
    seconds: float,
) -> None:
    """AudioBufferProcessor resamples to its sample_rate; WAV duration ≈ wall-clock."""
    buf = AudioBufferProcessor(
        num_channels=1,
        auto_start_recording=False,
        sample_rate=pipeline_rate,
    )
    _prime_buffer(buf, pipeline_rate)

    user = InputAudioRawFrame(
        audio=_pcm_silence(pipeline_rate, seconds),
        sample_rate=pipeline_rate,
        num_channels=1,
    )
    bot = OutputAudioRawFrame(
        audio=_pcm_silence(tts_frame_rate, seconds),
        sample_rate=tts_frame_rate,
        num_channels=1,
    )
    await buf._process_recording(user)
    await buf._process_recording(bot)
    buf._align_track_buffers()
    merged = buf.merge_audio_buffers()

    wav = wav_bytes(merged, pipeline_rate, 1)
    duration, header_rate = _wav_duration_seconds(wav)
    assert header_rate == pipeline_rate
    # After sync/align, duration should be ~seconds (not 1.5–2× from rate mismatch).
    assert duration == pytest.approx(seconds, abs=0.05)


@pytest.mark.asyncio
async def test_mislabeled_24k_as_16k_inflates_duration_without_native_label() -> None:
    """Documents the old bug: 24 kHz PCM tagged 16 kHz + buffer@24k stretches ~1.5×.

    This is why Orpheus must label frames at 24 kHz and we record at pipeline rate
    after transport (which has already done a correct 24→16 resample).
    """
    real_seconds = 0.4
    fake_label = 16000
    true_rate = 24000
    pcm = _pcm_silence(true_rate, real_seconds)

    buf = AudioBufferProcessor(
        num_channels=1,
        auto_start_recording=False,
        sample_rate=true_rate,
    )
    _prime_buffer(buf, true_rate)

    await buf._process_recording(
        OutputAudioRawFrame(audio=pcm, sample_rate=fake_label, num_channels=1)
    )
    buf._align_track_buffers()
    merged = buf.merge_audio_buffers()
    duration, _ = _wav_duration_seconds(wav_bytes(merged, true_rate, 1))
    # Wrong label stretches playback: clearly longer than real wall-clock (~1.5×).
    assert duration > real_seconds * 1.25
    assert duration == pytest.approx(real_seconds * (true_rate / fake_label), abs=0.1)


def test_factory_uses_stock_pipecat_recording_placement() -> None:
    """Stock Pipecat order — no conditional before-transport / recording rate kwarg."""
    src = inspect.getsource(build_pipeline_components)
    compact = "".join(src.split())
    assert "capture_tts_before_transport" not in src
    assert "recording_sample_rate" not in compact
    assert "transport.output(),audiobuffer" in compact
    assert "FastAPIWebsocketTransport" in src
    assert "RecordingAwareWebsocketTransport" not in src


def test_pipeline_components_signature_has_no_recording_sample_rate() -> None:
    sig = inspect.signature(build_pipeline_components)
    assert "recording_sample_rate" not in sig.parameters


def test_on_audio_data_handler_passes_pipecat_reported_rate() -> None:
    """recording.py must use the callback sample_rate for WAV (not a hard-coded rate)."""
    from apps.runtime.services.pipecat.events import recording as recording_mod

    src = inspect.getsource(recording_mod.register_recording_handlers)
    compact = "".join(src.split())
    assert "audio_sample_rate" in src
    assert "wav_bytes(audio,audio_sample_rate,num_channels)" in compact
