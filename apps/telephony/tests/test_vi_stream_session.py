"""VI stream session helpers."""

from __future__ import annotations

import pytest

from apps.telephony.providers.vi.stream_session import _caller_phone


@pytest.mark.parametrize(
    ("cli", "expected"),
    [
        ("9900112233", "919900112233"),
        ("+91 99001-12233", "919900112233"),
        ("09900112233", "919900112233"),
        ("+14155550100", "14155550100"),
        ("unknown", None),
        ("", None),
    ],
)
def test_caller_phone_is_digits_with_country_code(cli, expected):
    assert _caller_phone(cli) == expected
