"""Shared test fixtures for runtime routing tests."""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

# Avoid loading pipecat when only exercising HTTP/WebSocket routing.
_mock_runners = MagicMock()
_mock_runners.run_telephony_bot = AsyncMock()
_mock_runners.run_websocket_bot = AsyncMock()
sys.modules["apps.runtime.services.pipecat.runners"] = _mock_runners

from apps.runtime.app import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
