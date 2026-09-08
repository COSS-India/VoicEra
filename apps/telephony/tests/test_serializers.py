"""Tests for telephony frame serializer factory."""

from __future__ import annotations

import pytest

from apps.telephony.serializers import create_frame_serializer


@pytest.mark.parametrize("provider", ["vobiz", "plivo", "Vobiz", "Plivo"])
def test_create_frame_serializer_known_providers(provider: str) -> None:
    serializer = create_frame_serializer(
        provider,
        stream_sid="stream-1",
        call_sid="call-1",
        sample_rate=8000,
    )
    assert serializer is not None
    assert type(serializer).__name__ in ("VobizFrameSerializer", "PlivoFrameSerializer")


def test_vobiz_16k_serializer() -> None:
    serializer = create_frame_serializer(
        "vobiz",
        stream_sid="stream-1",
        call_sid="call-1",
        sample_rate=16000,
    )
    assert type(serializer).__name__ == "VobizFrameSerializer"


def test_unsupported_provider() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        create_frame_serializer(
            "twilio",
            stream_sid="stream-1",
            call_sid="call-1",
        )


def test_empty_provider_rejected() -> None:
    with pytest.raises(ValueError, match="provider id is required"):
        create_frame_serializer(
            "",
            stream_sid="stream-1",
            call_sid="call-1",
        )
