"""Outbound and inbound call routes."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterator

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.auth import get_current_user
from app.config import settings
from app.models.schemas import (
    CallAnalyticsResponse,
    CallLogListResponse,
    CallLogResponse,
    CallLogUpdateRequest,
    CallMetricsBody,
    CallMetricsResponse,
    CallTranscriptTurnsResponse,
    CallWebhookDeliveryResponse,
    InboundCallRegisterRequest,
    InboundCallRegisterResponse,
    OutboundCallRequest,
    OutboundCallResponse,
    WebCallRegisterRequest,
    WebCallRegisterResponse,
)
from app.services import call_webhook_service, member_service, org_service
from app.services.call_transcript_service import TranscriptUnavailableError, load_turns
from app.services.call_log_service import (
    CallLogNotFoundError,
    call_list_filters,
    count_call_logs_by_org,
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
from app.services.outbound_call_service import OutboundCallError, initiate_outbound_call
from app.services.web_call_service import WebCallError, register_web_call
from app.storage.minio_client import MinIOStorage

router = APIRouter(prefix="/calls", tags=["calls"])


def _require_active_org(current_user: dict[str, Any]) -> str:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active organisation in token",
        )
    return str(org_id)


def _as_utc(value: datetime) -> datetime:
    """Naive datetimes are UTC; aware ones are converted to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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


def _raise_call_not_found(exc: CallLogNotFoundError) -> None:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=str(exc),
    ) from exc


def _raise_call_metrics_not_found(exc: CallMetricsNotFoundError) -> None:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=str(exc),
    ) from exc


def _artifact_content_type(object_name: str, default: str) -> str:
    if object_name.endswith(".wav"):
        return "audio/wav"
    if object_name.endswith(".mp3"):
        return "audio/mpeg"
    if object_name.endswith(".txt"):
        return "text/plain; charset=utf-8"
    return default


def _stream_minio_object(bucket_name: str, object_name: str, content_type: str):
    storage = MinIOStorage()

    def iterator() -> Iterator[bytes]:
        response = storage.client.get_object(bucket_name, object_name)
        try:
            for chunk in response.stream(32 * 1024):
                yield chunk
        finally:
            response.close()
            response.release_conn()

    return StreamingResponse(iterator(), media_type=content_type)


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


@router.get("/{call_id}/recording")
async def get_call_recording(
    call_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> StreamingResponse:
    """Stream the call recording from MinIO."""
    org_id = _require_active_org(current_user)
    try:
        call = get_call_log(org_id, call_id)
    except CallLogNotFoundError as exc:
        _raise_call_not_found(exc)

    recording_url = call.get("recording_url")
    if not recording_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recording not found for this call",
        )

    parsed = MinIOStorage.parse_minio_url(str(recording_url))
    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid recording URL on call log",
        )

    bucket_name, object_name = parsed
    storage = MinIOStorage()
    if not storage.object_exists(bucket_name, object_name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Recording file not found: {object_name}",
        )

    content_type = _artifact_content_type(object_name, "audio/wav")
    return _stream_minio_object(bucket_name, object_name, content_type)


@router.get("/{call_id}/transcript")
async def get_call_transcript(
    call_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> StreamingResponse:
    """Stream the call transcript from MinIO."""
    org_id = _require_active_org(current_user)
    try:
        call = get_call_log(org_id, call_id)
    except CallLogNotFoundError as exc:
        _raise_call_not_found(exc)

    transcript_url = call.get("transcript_url")
    if not transcript_url:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transcript not found for this call",
        )

    parsed = MinIOStorage.parse_minio_url(str(transcript_url))
    if not parsed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid transcript URL on call log",
        )

    bucket_name, object_name = parsed
    storage = MinIOStorage()
    if not storage.object_exists(bucket_name, object_name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Transcript file not found: {object_name}",
        )

    content_type = _artifact_content_type(object_name, "text/plain; charset=utf-8")
    return _stream_minio_object(bucket_name, object_name, content_type)


@router.get("/{call_id}/transcript/turns", response_model=CallTranscriptTurnsResponse)
async def get_call_transcript_turns(
    call_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> CallTranscriptTurnsResponse:
    """The call transcript as ordered turns (caller and agent) in JSON."""
    org_id = _require_active_org(current_user)
    try:
        call = get_call_log(org_id, call_id)
    except CallLogNotFoundError as exc:
        _raise_call_not_found(exc)
    try:
        turns = load_turns(call)
    except TranscriptUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=exc.reason,
        ) from exc
    return CallTranscriptTurnsResponse(call_id=call_id, turn_count=len(turns), turns=turns)


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
    """Upsert pipeline metrics for one call (bot JWT supported; the stored
    record is only replaced by a payload with more answered user turns — see
    call_metrics_service.upsert_call_metrics)."""
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
    agent_id: str | None = Query(default=None, description="Only calls on this agent"),
    campaign_id: str | None = Query(default=None, description="Only calls in this campaign"),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="initiated, ringing, in_progress, completed or failed",
    ),
    call_response: str | None = Query(
        default=None,
        description="pending, answered, busy, no_answer, failed or cancelled",
    ),
    call_type: str | None = Query(default=None, description="outbound, inbound or web"),
    created_from: datetime | None = Query(
        default=None,
        description="Created at or after this time (ISO 8601; no offset = UTC)",
    ),
    created_to: datetime | None = Query(
        default=None,
        description="Created before this time (ISO 8601; no offset = UTC)",
    ),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> CallLogListResponse:
    """List call logs for an organisation, newest first (Bearer; must be a member).

    Every filter is optional and they combine with AND; ``total`` counts the
    filtered set.
    """
    if created_from and created_to and _as_utc(created_from) >= _as_utc(created_to):
        raise HTTPException(
            status_code=422,
            detail="created_from must be before created_to",
        )
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

    filters = call_list_filters(
        agent_id=agent_id,
        campaign_id=campaign_id,
        status=status_filter,
        call_response=call_response,
        call_type=call_type,
        created_from=created_from,
        created_to=created_to,
    )
    logs = list_call_logs_by_org(org_id, limit=limit, offset=offset, filters=filters)
    total = count_call_logs_by_org(org_id, filters=filters)
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


@router.get("/{call_id}/webhook", response_model=CallWebhookDeliveryResponse)
async def get_call_webhook(
    call_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Post-call webhook delivery status for one call."""
    org_id = _require_active_org(current_user)
    delivery = call_webhook_service.get_delivery(org_id, call_id)
    if not delivery:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No webhook delivery for call: {call_id}",
        )
    return delivery


@router.post(
    "/{call_id}/webhook/redeliver",
    response_model=CallWebhookDeliveryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def redeliver_call_webhook(
    call_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Queue the call's webhook to be sent again now (attempt count resets).

    Works for a call that never had a delivery as long as it has ended and
    its agent has an enabled webhook.
    """
    org_id = _require_active_org(current_user)
    delivery = call_webhook_service.redeliver(org_id, call_id)
    if not delivery:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Call has not ended or its agent has no enabled webhook",
        )
    return delivery


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
