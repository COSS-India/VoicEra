"""Outbound and inbound call routes."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from functools import partial
from pathlib import PurePosixPath
from typing import Any, Iterator, Literal, NoReturn
from urllib.parse import unquote

import urllib3
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from minio.error import MinioException

from app.auth import get_current_user, verify_api_key
from app.config import settings
from app.services.eventlog import Actor, Resource, Target, emit, request_context
from app.services.eventlog.registry import (
    CALL_PROVIDER_RECORDING_DOWNLOADED,
    CALL_PROVIDER_RECORDING_VIEWED,
    CALL_RECORDING_DOWNLOADED,
    CALL_RECORDING_VIEWED,
    CALL_TRANSCRIPT_DOWNLOADED,
    CALL_TRANSCRIPT_VIEWED,
    EventType,
)
from app.models.schemas import (
    CallAnalyticsResponse,
    CallLogListResponse,
    CallLogResponse,
    CallLogUpdateRequest,
    CallMetricsBody,
    CallMetricsResponse,
    InboundCallRegisterRequest,
    InboundCallRegisterResponse,
    OutboundCallRegisterRequest,
    OutboundCallRegisterResponse,
    OutboundCallRequest,
    OutboundCallResponse,
    WebCallRegisterRequest,
    WebCallRegisterResponse,
)
from app.services import agent_service, member_service, org_service
from app.services.call_log_service import (
    CallLogListFilters,
    CallLogNotFoundError,
    count_call_logs,
    find_call_log_by_provider_sid,
    get_call_log,
    get_org_call_analytics,
    list_call_logs_by_org,
    patch_call_log,
    patch_call_log_by_provider_sid,
    transform_call_log_urls,
)
from app.services.call_metrics_service import (
    CallMetricsNotFoundError,
    get_call_metrics,
    upsert_call_metrics,
)
from app.services.inbound_call_service import InboundCallError, register_inbound_call
from app.services.outbound_call_service import (
    OutboundCallError,
    initiate_outbound_call,
    register_outbound_call,
)
from app.services.web_call_service import WebCallError, register_web_call
from app.storage.minio_client import MinIOStorage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calls", tags=["calls"])

# MinIO failures other than a missing object: S3/server errors and transport
# errors (connection refused, retries exhausted) from the underlying urllib3.
_STORAGE_ERRORS: tuple[type[Exception], ...] = (MinioException, urllib3.exceptions.HTTPError)


def _require_active_org(current_user: dict[str, Any]) -> str:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active organisation in token",
        )
    return str(org_id)


def _raise_outbound_error(exc: OutboundCallError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail=exc.message,
    ) from exc


def _raise_inbound_error(exc: InboundCallError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail=exc.message,
    ) from exc


def _raise_web_call_error(exc: WebCallError) -> None:
    raise HTTPException(
        status_code=exc.status_code,
        detail=exc.message,
    ) from exc


def _call_related(org_id: str, call: dict[str, Any]) -> list[Resource]:
    """The call's agent and campaign, for its audit events.

    The agent is named as it is now, or as it was on the call if since deleted.
    ``get_call_log`` already resolved the campaign name.
    """
    related: list[Resource] = []
    agent_id = call.get("agent_id")
    if agent_id:
        name = agent_service.agent_name_for_audit(org_id, agent_id, call.get("agent_name"))
        related.append(Resource("agent", str(agent_id), name))
    campaign_id = call.get("campaign_id")
    if campaign_id:
        related.append(Resource("campaign", str(campaign_id), call.get("campaign_name")))
    return related


def _raise_call_not_found(exc: CallLogNotFoundError) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=str(exc),
    ) from exc


def _raise_call_metrics_not_found(exc: CallMetricsNotFoundError) -> None:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=str(exc),
    ) from exc


# Known artifact formats: object suffix -> (content type, download extension).
# A ``None`` content type keeps the artifact's default.
_ARTIFACT_FORMATS: dict[str, tuple[str | None, str]] = {
    ".wav": ("audio/wav", "wav"),
    ".mp3": ("audio/mpeg", "mp3"),
    ".txt": ("text/plain; charset=utf-8", "txt"),
    ".json": (None, "json"),
}


def _artifact_format(object_name: str) -> tuple[str | None, str]:
    return _ARTIFACT_FORMATS.get(PurePosixPath(object_name).suffix.lower(), (None, "bin"))


def _artifact_content_type(object_name: str, default: str) -> str:
    return _artifact_format(object_name)[0] or default


def _stream_minio_object(
    bucket_name: str,
    object_name: str,
    content_type: str,
    *,
    storage: MinIOStorage | None = None,
    headers: dict[str, str] | None = None,
) -> StreamingResponse:
    storage = storage or MinIOStorage()

    def iterator() -> Iterator[bytes]:
        response = storage.client.get_object(bucket_name, object_name)
        try:
            for chunk in response.stream(32 * 1024):
                yield chunk
        finally:
            response.close()
            response.release_conn()

    return StreamingResponse(iterator(), media_type=content_type, headers=headers)


@router.post(
    "/outbound",
    response_model=OutboundCallResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_outbound_call(
    body: OutboundCallRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Initiate an outbound call and register a CallLog with status initiated."""
    org_id = _require_active_org(current_user)
    try:
        return await initiate_outbound_call(
            org_id,
            body.agent_id,
            body.to_number,
            from_number=body.from_number,
            custom_variables=body.custom_variables,
        )
    except OutboundCallError as exc:
        _raise_outbound_error(exc)


@router.post(
    "/outbound/register",
    response_model=OutboundCallRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_outbound_call_log(
    body: OutboundCallRegisterRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Register an outbound CallLog when the voice runtime stream starts (no dial)."""
    org_id = _require_active_org(current_user)
    try:
        return register_outbound_call(
            org_id,
            body.agent_id,
            provider_call_sid=body.provider_call_sid,
            from_number=body.from_number,
            to_number=body.to_number,
        )
    except OutboundCallError as exc:
        _raise_outbound_error(exc)


@router.post(
    "/inbound",
    response_model=InboundCallRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_inbound_call(
    body: InboundCallRegisterRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Register an inbound call when the voice runtime answer webhook fires."""
    org_id = _require_active_org(current_user)
    try:
        return register_inbound_call(
            org_id,
            body.agent_id,
            provider_call_sid=body.provider_call_sid,
            from_number=body.from_number,
            to_number=body.to_number,
        )
    except InboundCallError as exc:
        _raise_inbound_error(exc)


@router.post(
    "/web",
    response_model=WebCallRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_web_call(
    body: WebCallRegisterRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Register a browser websocket session for CallLog artifacts."""
    org_id = _require_active_org(current_user)
    try:
        return register_web_call(
            org_id,
            body.agent_id,
            custom_variables=body.custom_variables,
        )
    except WebCallError as exc:
        _raise_web_call_error(exc)


@router.get("/by-provider-sid/{provider_call_sid}", response_model=CallLogResponse)
async def get_call_by_provider_sid(
    provider_call_sid: str,
    _: bool = Depends(verify_api_key),
) -> dict[str, Any]:
    """Resolve a CallLog by provider SID (voice server; X-API-Key)."""
    sid = unquote(provider_call_sid).strip()
    doc = find_call_log_by_provider_sid(sid)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Call log not found for provider sid: {sid}",
        )
    return transform_call_log_urls(doc, api_prefix=settings.API_V1_PREFIX)


@router.patch("/by-provider-sid/{provider_call_sid}", response_model=CallLogResponse)
async def patch_call_by_provider_sid(
    provider_call_sid: str,
    body: CallLogUpdateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Patch a CallLog by telephony provider SID (runtime hangup callbacks)."""
    org_id = _require_active_org(current_user)
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )
    try:
        doc = patch_call_log_by_provider_sid(org_id, provider_call_sid, patch)
    except CallLogNotFoundError as exc:
        _raise_call_not_found(exc)
    return transform_call_log_urls(doc, api_prefix=settings.API_V1_PREFIX)


@router.patch("/{call_id}", response_model=CallLogResponse)
async def patch_call(
    call_id: str,
    body: CallLogUpdateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Patch artifact URLs on a CallLog (bot JWT supported)."""
    org_id = _require_active_org(current_user)
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )
    try:
        doc = patch_call_log(org_id, call_id, patch)
    except CallLogNotFoundError as exc:
        _raise_call_not_found(exc)
    return transform_call_log_urls(doc, api_prefix=settings.API_V1_PREFIX)


ArtifactMode = Literal["view", "download"]


@dataclass(frozen=True)
class _Artifact:
    url_field: str
    file_stem: str
    file_label: str
    missing_detail: str
    invalid_detail: str
    default_content_type: str


ARTIFACTS: dict[str, _Artifact] = {
    "recording": _Artifact(
        url_field="recording_url",
        file_stem="recording",
        file_label="Recording",
        missing_detail="Recording not found for this call",
        invalid_detail="Invalid recording URL on call log",
        default_content_type="audio/wav",
    ),
    "provider_recording": _Artifact(
        url_field="provider_recording_url",
        file_stem="provider-recording",
        file_label="Recording",
        missing_detail="Provider recording not found for this call",
        invalid_detail="Invalid provider recording URL on call log",
        default_content_type="audio/wav",
    ),
    "transcript": _Artifact(
        url_field="transcript_url",
        file_stem="transcript",
        file_label="Transcript",
        missing_detail="Transcript not found for this call",
        invalid_detail="Invalid transcript URL on call log",
        default_content_type="text/plain; charset=utf-8",
    ),
}

ARTIFACT_EVENTS: dict[tuple[str, ArtifactMode], EventType] = {
    ("recording", "view"): CALL_RECORDING_VIEWED,
    ("recording", "download"): CALL_RECORDING_DOWNLOADED,
    ("provider_recording", "view"): CALL_PROVIDER_RECORDING_VIEWED,
    ("provider_recording", "download"): CALL_PROVIDER_RECORDING_DOWNLOADED,
    ("transcript", "view"): CALL_TRANSCRIPT_VIEWED,
    ("transcript", "download"): CALL_TRANSCRIPT_DOWNLOADED,
}

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9_-]")


class _ArtifactError(Exception):
    def __init__(self, reason: str, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.status_code = status_code
        self.detail = detail

    def http(self) -> HTTPException:
        return HTTPException(status_code=self.status_code, detail=self.detail)


def _resolve_artifact(
    storage: MinIOStorage, call: dict[str, Any], artifact: _Artifact
) -> tuple[str, str]:
    artifact_url = call.get(artifact.url_field)
    if not artifact_url:
        raise _ArtifactError(
            "artifact_missing", status.HTTP_404_NOT_FOUND, artifact.missing_detail
        )

    parsed = MinIOStorage.parse_minio_url(str(artifact_url))
    if not parsed:
        raise _ArtifactError(
            "invalid_artifact_url", status.HTTP_400_BAD_REQUEST, artifact.invalid_detail
        )

    bucket_name, object_name = parsed
    try:
        exists = storage.object_exists(bucket_name, object_name)
    except _STORAGE_ERRORS as exc:
        logger.exception("Artifact storage check failed for %s/%s", bucket_name, object_name)
        raise _ArtifactError(
            "storage_unavailable",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Call artifact storage is unavailable. Try again shortly.",
        ) from exc
    if not exists:
        raise _ArtifactError(
            "artifact_missing",
            status.HTTP_404_NOT_FOUND,
            f"{artifact.file_label} file not found: {object_name}",
        )
    return bucket_name, object_name


def _download_disposition(call: dict[str, Any], artifact: _Artifact, object_name: str) -> str:
    """Attachment filename from the stored call ID and an allow-listed extension."""
    call_id = _UNSAFE_FILENAME_CHARS.sub("", str(call.get("call_id") or "")) or "call"
    extension = _artifact_format(object_name)[1]
    return f'attachment; filename="{call_id}-{artifact.file_stem}.{extension}"'


def _serve_artifact(
    request: Request,
    current_user: dict[str, Any],
    call_id: str,
    artifact_name: str,
    mode: ArtifactMode,
) -> StreamingResponse:
    """Authorise, record the access, then stream one call artifact from MinIO."""
    org_id = _require_active_org(current_user)
    artifact = ARTIFACTS[artifact_name]
    record = partial(
        emit,
        ARTIFACT_EVENTS[(artifact_name, mode)],
        org_id=org_id,
        actor=Actor.from_user(current_user),
        target=Target("call", call_id),
        context=request_context(request),
    )
    try:
        call = get_call_log(org_id, call_id)
    except CallLogNotFoundError as exc:
        record(outcome="failure", data={"reason": "call_not_found"})
        _raise_call_not_found(exc)

    record = partial(record, related=_call_related(org_id, call))
    try:
        storage = MinIOStorage()
        bucket_name, object_name = _resolve_artifact(storage, call, artifact)
    except _ArtifactError as exc:
        record(outcome="failure", data={"reason": exc.reason})
        raise exc.http() from exc

    # Recorded before the first byte, so a client disconnect cannot skip it.
    record(data={"object_key": object_name})
    headers = (
        {"Content-Disposition": _download_disposition(call, artifact, object_name)}
        if mode == "download"
        else None
    )
    content_type = _artifact_content_type(object_name, artifact.default_content_type)
    return _stream_minio_object(
        bucket_name, object_name, content_type, storage=storage, headers=headers
    )


@router.get("/{call_id}/recording")
def get_call_recording(
    call_id: str,
    request: Request,
    mode: ArtifactMode = Query("view"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> StreamingResponse:
    """Stream the system (Pipecat) call recording from MinIO."""
    return _serve_artifact(request, current_user, call_id, "recording", mode)


@router.get("/{call_id}/provider-recording")
def get_call_provider_recording(
    call_id: str,
    request: Request,
    mode: ArtifactMode = Query("view"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> StreamingResponse:
    """Stream the carrier / provider recording from MinIO."""
    return _serve_artifact(request, current_user, call_id, "provider_recording", mode)


@router.get("/{call_id}/transcript")
def get_call_transcript(
    call_id: str,
    request: Request,
    mode: ArtifactMode = Query("view"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> StreamingResponse:
    """Stream the call transcript from MinIO."""
    return _serve_artifact(request, current_user, call_id, "transcript", mode)


@router.get("/{call_id}/metrics", response_model=CallMetricsResponse)
async def get_call_metrics_route(
    call_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Fetch pipeline metrics for one call (bot JWT supported)."""
    org_id = _require_active_org(current_user)
    try:
        return get_call_metrics(org_id, call_id)
    except CallLogNotFoundError as exc:
        _raise_call_not_found(exc)
    except CallMetricsNotFoundError as exc:
        _raise_call_metrics_not_found(exc)


@router.put("/{call_id}/metrics", response_model=CallMetricsResponse)
async def put_call_metrics(
    call_id: str,
    body: CallMetricsBody,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Upsert pipeline metrics for one call (bot JWT supported; write-once)."""
    org_id = _require_active_org(current_user)
    try:
        return upsert_call_metrics(org_id, call_id, body.model_dump())
    except CallLogNotFoundError as exc:
        _raise_call_not_found(exc)


@router.get("/org/{org_id}", response_model=CallLogListResponse)
async def list_org_calls(
    org_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    campaign_id: str | None = Query(default=None),
    exclude_campaign: bool = Query(
        default=False,
        description="If true, return only one-off calls (no campaign_id)",
    ),
    agent_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    call_type: str | None = Query(default=None),
    call_response: str | None = Query(default=None),
    created_after: str | None = Query(
        default=None,
        description="ISO-8601 lower bound on created_at (inclusive)",
    ),
    created_before: str | None = Query(
        default=None,
        description="ISO-8601 upper bound on created_at (inclusive)",
    ),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> CallLogListResponse:
    """List call logs for an organisation (Bearer; must be a member of that org)."""
    token_org_id = _require_active_org(current_user)
    if org_id != token_org_id:
        membership = member_service.get_membership(current_user["email"], org_id)
        if not membership:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access calls for this organisation",
            )

    if not org_service.get_organisation(org_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation not found",
        )

    if exclude_campaign and campaign_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="exclude_campaign and campaign_id cannot be combined",
        )

    filters = CallLogListFilters(
        campaign_id=campaign_id,
        exclude_campaign=exclude_campaign,
        agent_id=agent_id,
        status=status_filter,
        call_type=call_type,
        call_response=call_response,
        created_after=created_after,
        created_before=created_before,
    )
    logs = list_call_logs_by_org(org_id, limit=limit, offset=offset, filters=filters)
    total = count_call_logs(org_id, filters)
    return CallLogListResponse(
        calls=[
            transform_call_log_urls(log, api_prefix=settings.API_V1_PREFIX)
            for log in logs
        ],
        limit=limit,
        offset=offset,
        total=total,
    )


@router.get("/org/{org_id}/analytics", response_model=CallAnalyticsResponse)
async def get_org_call_analytics_route(
    org_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> CallAnalyticsResponse:
    """All-time call analytics for an organisation (Bearer; must be a member of that org)."""
    token_org_id = _require_active_org(current_user)
    if org_id != token_org_id:
        membership = member_service.get_membership(current_user["email"], org_id)
        if not membership:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not authorized to access calls for this organisation",
            )

    if not org_service.get_organisation(org_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organisation not found",
        )

    return CallAnalyticsResponse(**get_org_call_analytics(org_id))


@router.get("/{call_id}", response_model=CallLogResponse)
async def get_call(
    call_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Fetch one call log by id (same organisation only; bot JWT supported)."""
    org_id = _require_active_org(current_user)
    try:
        doc = get_call_log(org_id, call_id)
    except CallLogNotFoundError as exc:
        _raise_call_not_found(exc)
    return transform_call_log_urls(doc, api_prefix=settings.API_V1_PREFIX)
