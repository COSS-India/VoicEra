"""FastAPI voice runtime: telephony /answer webhook + /agent WebSocket (port 7860)."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from loguru import logger

from apps.runtime.routes import agent, health, plivo_telephony, telephony, vi_telephony
from apps.runtime.services.storage.object_storage import sse_mode, verify_sse_support


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("Object storage SSE mode={}", sse_mode())
    await verify_sse_support()
    yield


app = FastAPI(
    title="Voicera Runtime",
    description="Telephony answer webhook + Pipecat WebSocket pipeline",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(telephony.router)
app.include_router(agent.router)
app.include_router(vi_telephony.router)
app.include_router(plivo_telephony.router)


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
