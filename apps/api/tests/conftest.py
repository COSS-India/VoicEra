"""Ensure ``app`` and ``apps`` imports resolve when tests run from the repo root."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parents[1]
VOICERA_ROOT = Path(__file__).resolve().parents[3]

for path in (str(API_ROOT), str(VOICERA_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)


class _EventLoopEmitDetector(logging.Handler):
    def __init__(self, message: str) -> None:
        super().__init__(level=logging.ERROR)
        self.message = message
        self.seen = False

    def emit(self, record: logging.LogRecord) -> None:
        if record.getMessage() == self.message:
            self.seen = True


@pytest.fixture(autouse=True)
def eventlog_loop_guard():
    """Fail any test in which ``emit()`` blocked the event loop.

    Uses its own handler on the ``voicera.eventlog`` logger rather than
    ``caplog.set_level``, which would raise caplog's capture level for every test.
    A test that triggers the warning on purpose requests this fixture and resets
    ``seen``.
    """
    from app.eventlog import EVENT_LOOP_WARNING

    detector = _EventLoopEmitDetector(EVENT_LOOP_WARNING)
    logger = logging.getLogger("voicera.eventlog")
    logger.addHandler(detector)
    try:
        yield detector
    finally:
        logger.removeHandler(detector)
    if detector.seen:
        pytest.fail("eventlog.emit() was called on the event loop thread")
