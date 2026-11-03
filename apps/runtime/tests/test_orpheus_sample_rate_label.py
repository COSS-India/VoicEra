"""Orpheus TTS must label PCM as 24 kHz so transport/AudioBuffer resample correctly."""

from __future__ import annotations

import inspect

from apps.providers.adapters.bhashini.catalog import ORPHEUS_SAMPLE_RATE
from apps.providers.adapters.bhashini.orpheus_tts import BhashiniOrpheusTTSService
from apps.providers.local.indic_orpheus.catalog import SAMPLE_RATE
from apps.providers.local.indic_orpheus.tts import IndicOrpheusTTSService


def test_indic_orpheus_forces_24k_init_even_if_pipeline_requests_16k() -> None:
    svc = IndicOrpheusTTSService(
        api_key="x",
        base_url="http://localhost",
        sample_rate=16000,
    )
    assert svc._init_sample_rate == SAMPLE_RATE == 24000


def test_indic_orpheus_run_tts_yields_native_rate_constant() -> None:
    src = inspect.getsource(IndicOrpheusTTSService.run_tts)
    assert "SAMPLE_RATE" in src
    assert "self.sample_rate" not in src.split("TTSAudioRawFrame")[1].split(")")[0]


def test_indic_orpheus_start_pins_rate() -> None:
    src = inspect.getsource(IndicOrpheusTTSService.start)
    assert "self._sample_rate = SAMPLE_RATE" in src


def test_bhashini_orpheus_forces_24k_init() -> None:
    svc = BhashiniOrpheusTTSService(
        auth_token="tok",
        function_id="fn",
        sample_rate=16000,
    )
    assert svc._init_sample_rate == ORPHEUS_SAMPLE_RATE == 24000


def test_bhashini_orpheus_start_pins_rate() -> None:
    src = inspect.getsource(BhashiniOrpheusTTSService.start)
    assert "self._sample_rate = ORPHEUS_SAMPLE_RATE" in src
