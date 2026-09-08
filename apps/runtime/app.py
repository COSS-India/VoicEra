"""FastAPI voice runtime: telephony /answer webhook + /agent WebSocket (port 7860)."""

from __future__ import annotations

import os

from fastapi import FastAPI

from apps.runtime.routes import agent, health, telephony

app = FastAPI(
    title="Voicera Runtime",
    description="Telephony answer webhook + Pipecat WebSocket pipeline",
    version="0.1.0",
)

app.include_router(health.router)
app.include_router(telephony.router)
app.include_router(agent.router)


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
