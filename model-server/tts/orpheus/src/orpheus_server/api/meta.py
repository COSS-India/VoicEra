"""Liveness and metrics. Unauthenticated so probes and dashboards work."""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import FileResponse

router = APIRouter()

#: The demo page, beside this package in the image and in a checkout alike.
#: Resolved at call time rather than import time so a missing file is a 404 on
#: one route instead of a container that will not start.
_STATIC = Path(__file__).resolve().parents[3] / "static"


@router.get("/health", tags=["meta"], summary="Liveness and readiness")
async def health(request: Request, response: Response):
    """``ready`` flips true only after the model is loaded and warmup has finished.

    Returns 503 until then, so orchestrators hold traffic back rather than sending
    it to an engine that is still capturing CUDA graphs.
    """
    engine = request.app.state.engine
    settings = request.app.state.settings
    ready = engine.ready
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if ready else "loading",
        "ready": ready,
        "model": settings.server.model_name,
        "model_path": engine.model_path,
        "quantization": settings.model.quantization,
        "max_num_seqs": settings.engine.max_num_seqs,
        "streams_active": engine.metrics.streams_active,
    }


@router.get("/metrics", tags=["meta"], summary="Aggregate runtime counters")
async def metrics(request: Request):
    """Process-wide counters only.

    Per-request latency is deliberately absent: with many concurrent streams a
    shared ``last_ttfa`` reports whichever request finished most recently, which
    is misleading. Each response carries its own ``X-TTFA-Ms`` / ``X-RTF``
    instead, and the WebSocket ``done`` frame carries the full per-stream summary.
    """
    engine = request.app.state.engine
    return {
        **engine.metrics.snapshot(),
        "ready": engine.ready,
        "uptime_seconds": (
            round(time.time() - engine.started_at, 1) if engine.started_at else None
        ),
    }


@router.get("/demo", tags=["meta"], summary="Live synthesis demo page",
            response_class=FileResponse, include_in_schema=False)
async def demo():
    """A page for hearing the model rather than reading about it.

    Served by the model itself, not the gateway, for the same reason the STT
    slot does it this way: a model is a folder you copy into place, and its demo
    has to arrive with it. The gateway only forwards.

    Nothing about the page is specific to this model -- it reads the voice
    roster, the styles and its own title from the routes above, so the same file
    works in any TTS folder that serves them.
    """
    page = _STATIC / "demo.html"
    if not page.is_file():
        raise HTTPException(404, "no demo page shipped in this image")
    return FileResponse(page, media_type="text/html")
