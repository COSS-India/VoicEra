"""Ensure ``app`` and ``apps`` imports resolve when tests run from the repo root."""

from __future__ import annotations

import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
VOICERA_ROOT = Path(__file__).resolve().parents[3]

for path in (str(API_ROOT), str(VOICERA_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _no_ambient_platform_credentials(monkeypatch):
    """A PLATFORM_PROVIDER_AUTH in the developer's environment must not leak into tests.

    Tests that want platform credentials set them explicitly (see test_platform_auth.py).
    """
    try:
        from app.config import settings
        from app.services import platform_auth
    except Exception:  # an app import that needs env the test does not provide
        yield
        return
    monkeypatch.setattr(settings, "PLATFORM_PROVIDER_AUTH", "")
    platform_auth._credentials.cache_clear()
    yield
    platform_auth._credentials.cache_clear()
