"""FastAPI voice runtime: telephony /answer webhook + /agent WebSocket (port 7860)."""

from __future__ import annotations

import os

from fastapi import FastAPI

from apps.runtime.routes import agent, health, plivo_telephony, telephony, vi_telephony

app = FastAPI(
    title="Voicera Runtime",
    description="Telephony answer webhook + Pipecat WebSocket pipeline",
    version="0.1.0",
)

app.include_router(health.router)
app.include_router(telephony.router)
app.include_router(agent.router)
app.include_router(vi_telephony.router)
app.include_router(plivo_telephony.router)


def _configure_logging() -> None:
    """Default the runtime log level to INFO (loguru's own default is DEBUG).

    At DEBUG, Pipecat logs the assistant's text ("Generating TTS [...]"), which
    PII redaction does not cover.
    """
    import sys

    from loguru import logger

    level = os.getenv("RUNTIME_LOG_LEVEL", "INFO").strip().upper() or "INFO"
    logger.remove()
    logger.add(sys.stderr, level=level)


_configure_logging()


def main() -> None:
    import uvicorn

    host = os.getenv("RUNTIME_HOST", "0.0.0.0")
    port = int(os.getenv("RUNTIME_PORT", "7860"))
    uvicorn.run(
        "apps.runtime.app:app",
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
