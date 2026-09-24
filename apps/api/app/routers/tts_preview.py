"""Voice preview route: hear an unsaved TTS config speak arbitrary text."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.auth import get_current_user
from app.models.schemas import TtsPreviewRequest
from app.services.tts_preview_service import (
    TtsPreviewError,
    TtsPreviewErrorReason,
    generate_preview,
)

router = APIRouter(prefix="/tts", tags=["tts"])

_ERROR_STATUS: dict[TtsPreviewErrorReason, int] = {
    TtsPreviewErrorReason.EMPTY_TEXT: status.HTTP_400_BAD_REQUEST,
    TtsPreviewErrorReason.OVERSIZED: status.HTTP_413_CONTENT_TOO_LARGE,
    TtsPreviewErrorReason.INVALID_CONFIG: status.HTTP_422_UNPROCESSABLE_CONTENT,
    TtsPreviewErrorReason.UNSUPPORTED_VOICE: status.HTTP_422_UNPROCESSABLE_CONTENT,
    TtsPreviewErrorReason.NOT_CONFIGURED: status.HTTP_409_CONFLICT,
    TtsPreviewErrorReason.TIMEOUT: status.HTTP_504_GATEWAY_TIMEOUT,
    TtsPreviewErrorReason.UPSTREAM: status.HTTP_502_BAD_GATEWAY,
}


def _require_active_org(current_user: dict[str, Any]) -> str:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active organisation in token",
        )
    return str(org_id)


def _raise_preview_error(exc: TtsPreviewError) -> None:
    raise HTTPException(
        status_code=_ERROR_STATUS[exc.reason],
        detail=str(exc),
    ) from exc


@router.post("/preview")
async def preview_tts(
    body: TtsPreviewRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> Response:
    """Synthesize ``body.text`` with the given (unsaved) TTS config."""
    org_id = _require_active_org(current_user)
    try:
        audio = await generate_preview(org_id, body.tts_config, body.language, body.text)
    except TtsPreviewError as exc:
        _raise_preview_error(exc)
        raise  # unreachable; satisfies type checkers

    return Response(content=audio, media_type="audio/wav")
