"""Hold-audio WAV/MP3 upload/delete API (org-scoped MinIO objects)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status

from app.auth import get_current_user
from app.models.schemas import HoldAudioDeleteResponse, HoldAudioUploadResponse
from app.services import hold_audio_service

router = APIRouter(prefix="/hold-audio", tags=["hold-audio"])


def _require_org_id(current_user: dict[str, Any]) -> str:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization",
        )
    return str(org_id)


@router.post(
    "/upload",
    response_model=HoldAudioUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_hold_audio(
    file: UploadFile = File(...),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> HoldAudioUploadResponse:
    """Upload a WAV or MP3 hold clip for the authenticated organisation."""
    org_id = _require_org_id(current_user)
    content = await file.read()
    try:
        meta = hold_audio_service.upload_clip(org_id, file.filename or "", content)
    except hold_audio_service.HoldAudioError as exc:
        detail = str(exc)
        code = (
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            if "too large" in detail.lower()
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=detail) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store uploaded file",
        ) from exc

    return HoldAudioUploadResponse(
        clip_id=meta["clip_id"],
        storage_key=meta["storage_key"],
        filename=meta["filename"],
    )


@router.delete(
    "/{clip_id}",
    response_model=HoldAudioDeleteResponse,
    status_code=status.HTTP_200_OK,
)
async def delete_hold_audio(
    clip_id: str,
    storage_key: str = Query(..., min_length=1),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> HoldAudioDeleteResponse:
    """Delete a hold clip from MinIO when the key belongs to this organisation."""
    org_id = _require_org_id(current_user)
    try:
        hold_audio_service.delete_clip(org_id, clip_id, storage_key)
    except hold_audio_service.HoldAudioError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return HoldAudioDeleteResponse(deleted=True)
