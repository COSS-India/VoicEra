"""Provider recording shared + VI webhook parse tests."""

from __future__ import annotations

from apps.telephony.provider_recording import recording_filename_for_url
from apps.telephony.providers.vi.recording import parse_hangup_recording_webhook


def test_vi_parse_hangup_recording_webhook_aliases() -> None:
    ref = parse_hangup_recording_webhook(
        {"recording_url": "https://cdn.example/r.wav?callid=abc"}
    )
    assert ref is not None
    assert ref.provider_call_sid == "abc"
    assert ref.recording_url == "https://cdn.example/r.wav?callid=abc"

    ref2 = parse_hangup_recording_webhook(
        {"RecordVoice": "https://cdn.example/r.wav?call_id=xyz"}
    )
    assert ref2 is not None
    assert ref2.provider_call_sid == "xyz"

    assert parse_hangup_recording_webhook({}) is None
    assert parse_hangup_recording_webhook({"recording_url": "  "}) is None


def test_vi_parse_extracts_call_id_from_path_filename() -> None:
    ref = parse_hangup_recording_webhook(
        {"recording_url": "https://cdn.example/recordings/vi-stream-789.wav"}
    )
    assert ref is not None
    assert ref.provider_call_sid == "vi-stream-789"


def test_vi_parse_missing_call_id() -> None:
    assert (
        parse_hangup_recording_webhook({"recording_url": "https://cdn.example/"})
        is None
    )


def test_recording_filename_for_url() -> None:
    assert (
        recording_filename_for_url("https://cdn.example/a/b.mp3?callid=1")
        == "provider_recording.mp3"
    )
    assert (
        recording_filename_for_url("https://cdn.example/a/b?callid=1")
        == "provider_recording.wav"
    )
