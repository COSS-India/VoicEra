"""Ensure ``app`` and ``apps`` imports resolve when tests run from the repo root."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
VOICERA_ROOT = Path(__file__).resolve().parents[3]

for path in (str(API_ROOT), str(VOICERA_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)


@pytest.fixture(autouse=True)
def _no_ambient_platform_credentials(monkeypatch):
    """Keep the developer's real ``PLATFORM_PROVIDER_AUTH`` out of the suite.

    Settings load the repository ``.env``, so a machine that actually has
    platform credentials configured would otherwise see different results —
    a provider resolving through the fallback instead of 404, or showing as
    authenticated when the test expects it not to be. Tests that want platform
    credentials set them explicitly.
    """
    from app.services import platform_auth

    monkeypatch.setattr(platform_auth.settings, "PLATFORM_PROVIDER_AUTH", "")
    platform_auth._credentials.cache_clear()
    yield
    platform_auth._credentials.cache_clear()
