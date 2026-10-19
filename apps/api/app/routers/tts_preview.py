"""Voice preview route: hear an unsaved TTS config speak arbitrary text."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.auth import get_current_user
from app.models.schemas import TtsPreviewRequest
from app.services.tts_preview_service import (
    PREVIEW_MEDIA_TYPE,
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
    TtsPreviewErrorReason.RATE_LIMITED: status.HTTP_429_TOO_MANY_REQUESTS,
    TtsPreviewErrorReason.TIMEOUT: status.HTTP_504_GATEWAY_TIMEOUT,
    TtsPreviewErrorReason.UPSTREAM: status.HTTP_502_BAD_GATEWAY,
}


# Status codes are shared by several reasons (400, 422), so preview errors carry
# a machine-readable ``code`` the frontend keys its user-facing message on.
_NO_ACTIVE_ORG_CODE = "no_active_org"


def _error_detail(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _require_active_org(current_user: dict[str, Any]) -> str:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_error_detail(_NO_ACTIVE_ORG_CODE, "No active organisation in token"),
        )
    return str(org_id)


def _to_http_error(exc: TtsPreviewError) -> HTTPException:
    headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None
    return HTTPException(
        status_code=_ERROR_STATUS[exc.reason],
        detail=_error_detail(exc.reason.value, str(exc)),
        headers=headers,
    )


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
        raise _to_http_error(exc) from exc

    return Response(content=audio, media_type=PREVIEW_MEDIA_TYPE)
