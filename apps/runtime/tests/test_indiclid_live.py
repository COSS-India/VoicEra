"""Live check of the language judge against the deployed IndicLID service.

Skipped unless INDICLID_URL (default http://192.168.0.218:8090) answers /health.
"""

from __future__ import annotations

import os

import httpx
import pytest

from apps.runtime.services.language_switch.lid.indiclid import IndicLidClient
from apps.runtime.services.language_switch.lid.judge import LanguageJudge

URL = os.environ.get("INDICLID_URL", "http://192.168.0.218:8090")
ALL = ("kn", "hi", "mr", "ta", "te")


def _reachable() -> bool:
    try:
        return httpx.get(f"{URL}/health", timeout=2.0).status_code == 200
    except Exception:  # noqa: BLE001
        return False


pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not _reachable(), reason="IndicLID service unreachable"),
]

# (id, active, main ASR text, Nemotron text, expected language)
CASES = [
    ("kn-native-both", "hi", "ನಮಸ್ಕಾರ ನೀವು ಹೇಗಿದ್ದೀರಿ", "ನಮಸ್ಕಾರ ನೀವು ಹೇಗಿದ್ದೀರಿ", "kn"),
    ("kn-main-hi-nemotron-kn", "hi", "नमस्कार आप कैसे हैं आज", "ನಮಸ್ಕಾರ ನೀವು ಹೇಗಿದ್ದೀರಿ ಇವತ್ತು", "kn"),
    ("ta-nemotron-native", "hi", "वणक्कम नीங்கள் எப்படி", "வணக்கம் நீங்கள் எப்படி இருக்கிறீர்கள்", "ta"),
    ("te-nemotron-native", "hi", "नमस्कारम मीरु ऎलाउन्नारु", "నమస్కారం మీరు ఎలా ఉన్నారు", "te"),
    ("mr-devanagari", "hi", "नमस्कार तुम्ही कसे आहात आज", "नमस्कार तुम्ही कसे आहात आज", "mr"),
    ("kn-active-devanagari-nemotron-stays", "kn", "ನಮಸ್ಕಾರ ನೀವು ಹೇಗಿದ್ದೀರಿ", "नमस्कार निवु हेगिद्दीरी", None),
    ("hi-stays-hi", "hi", "मुझे अपने खाते की जानकारी चाहिए", "मुझे अपने खाते की जानकारी चाहिए", None),
]


@pytest.mark.parametrize("case", CASES, ids=[c[0] for c in CASES])
async def test_live_judge(case) -> None:
    _id, active, main, nemotron, expected = case
    client = IndicLidClient(URL)
    try:
        evidence = await client.score([main, nemotron])
    finally:
        await client.aclose()
    judge = LanguageJudge(allowed_languages=ALL, active_language=active, cooldown_sec=0.0)
    decision = judge.decide(evidence[0], evidence[1])
    print(f"\n{_id}: {decision.outcome} {decision.language} {decision.reason} {decision.scores}")
    if expected is None:
        assert decision.outcome != "switch"
    else:
        assert decision.outcome == "switch" and decision.language == expected
