"""Campaign outbound calling API."""

from __future__ import annotations

import csv
import io
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse

from app.auth import get_current_user, verify_api_key
from app.constants.campaign import DEFAULT_CAMPAIGN_RETRY_CONFIG
from app.config import settings
from app.database_init import ROLE_ADMIN, ROLE_SUPER_ADMIN
from app.models.schemas import (
    CampaignCallStatusRequest,
    CampaignCsvUploadResponse,
    CampaignProgressResponse,
    CampaignResponse,
    CreateCampaignRequest,
    RedialCampaignRequest,
    SuccessResponse,
    UpdateCampaignRequest,
)
from app.services import agent_service
from app.services.agent_service import AgentNotFoundError
from app.services.call_log_service import list_call_logs_by_campaign, transform_call_log_urls
from app.services.campaign import campaign_repository as repo
from app.services.campaign.campaign_repository import CampaignNotFoundError, get_org_concurrent_limit
from app.services.campaign.runner import campaign_runner_service
from app.services.campaign.source_sync_factory import get_sync_service
from app.services.campaign.status_processor import handle_call_terminal
from app.services import phone_number_service
from app.storage.minio_client import MinIOStorage

router = APIRouter(prefix="/campaign", tags=["campaign"])

_DELETE_ROLES = frozenset({ROLE_SUPER_ADMIN, ROLE_ADMIN})


def _require_org(current_user: dict[str, Any]) -> str:
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(status_code=400, detail="No active organisation in token")
    return str(org_id)


def _require_delete_role(current_user: dict[str, Any]) -> None:
    if current_user.get("role") not in _DELETE_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can delete campaigns",
        )


def _to_campaign_response(doc: dict[str, Any]) -> CampaignResponse:
    return CampaignResponse(
        campaign_id=str(doc["campaign_id"]),
        org_id=str(doc["org_id"]),
        name=str(doc["name"]),
        agent_id=str(doc["agent_id"]),
        source_type=str(doc.get("source_type") or "csv"),
        source_id=str(doc["source_id"]),
        state=doc.get("state", "created"),
        total_rows=int(doc.get("total_rows") or 0),
        processed_rows=int(doc.get("processed_rows") or 0),
        failed_rows=int(doc.get("failed_rows") or 0),
        rate_limit_per_second=int(doc.get("rate_limit_per_second") or 1),
        retry_config=doc.get("retry_config") or {},
        orchestrator_metadata=doc.get("orchestrator_metadata") or {},
        from_number=doc.get("from_number"),
        created_by=doc.get("created_by"),
        created_at=doc.get("created_at"),
        updated_at=doc.get("updated_at"),
        started_at=doc.get("started_at"),
        completed_at=doc.get("completed_at"),
    )


def _count_agent_from_numbers(org_id: str, agent_id: str) -> int:
    count = 0
    try:
        agent = agent_service.get_agent(org_id, agent_id)
        if agent.get("linked_phone_number"):
            count += 1
    except AgentNotFoundError:
        pass
    for doc in phone_number_service.list_by_org(org_id):
        if doc.get("agent_id") == agent_id and doc.get("phone_number"):
            count += 1
    return count


def _validate_telephony_agent(org_id: str, agent_id: str) -> dict[str, Any]:
    try:
        agent = agent_service.get_agent(org_id, agent_id)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if str(agent.get("agent_category") or "") != "telephony":
        raise HTTPException(status_code=422, detail="Campaign requires a telephony agent")
    if _count_agent_from_numbers(org_id, agent_id) == 0:
        raise HTTPException(
            status_code=422,
            detail="Attach a phone number to this agent before creating a campaign",
        )
    return agent


def _validate_max_concurrency(org_id: str, agent_id: str, max_concurrency: int) -> None:
    org_limit = get_org_concurrent_limit(org_id)
    if max_concurrency > org_limit:
        raise HTTPException(
            status_code=400,
            detail=(
                f"max_concurrency ({max_concurrency}) cannot exceed org limit "
                f"({org_limit})"
            ),
        )


@router.post(
    "/upload",
    response_model=CampaignCsvUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_campaign_csv(
    file: UploadFile = File(...),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> CampaignCsvUploadResponse:
    """Upload a campaign contact CSV (same pattern as knowledge PDF upload)."""
    org_id = _require_org(current_user)
    filename = (file.filename or "").strip()
    if not filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only CSV files are allowed",
        )

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file",
        )
    if len(content) > settings.CAMPAIGN_MAX_CSV_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File too large (max {settings.CAMPAIGN_MAX_CSV_BYTES // (1024 * 1024)} MB)"
            ),
        )

    safe_name = filename.replace("/", "_").replace("\\", "_")
    source_id = f"campaigns/{org_id}/{uuid.uuid4()}_{safe_name}"
    storage = MinIOStorage()
    try:
        await storage.put_object_bytes(source_id, content, content_type="text/csv")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to store CSV: {exc}",
        ) from exc

    sync_service = get_sync_service("csv")
    validation = await sync_service.validate_source(source_id, org_id)
    if not validation.is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=validation.error.message if validation.error else "Invalid CSV",
        )

    rows = validation.rows or []
    phone_idx = (validation.headers or []).index("phone_number")
    contact_rows = sum(
        1
        for row in rows
        if len(row) > phone_idx and str(row[phone_idx]).strip()
    )
    return CampaignCsvUploadResponse(
        source_id=source_id,
        filename=safe_name,
        contact_rows=contact_rows,
    )


@router.post("/create", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    body: CreateCampaignRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> CampaignResponse:
    org_id = _require_org(current_user)
    _validate_telephony_agent(org_id, body.agent_id)
    _validate_max_concurrency(org_id, body.agent_id, body.max_concurrency)

    sync_service = get_sync_service(body.source_type)
    validation = await sync_service.validate_source(body.source_id, org_id)
    if not validation.is_valid:
        raise HTTPException(
            status_code=400,
            detail=validation.error.message if validation.error else "Invalid source",
        )

    orchestrator_metadata: dict[str, Any] = {
        "max_concurrency": body.max_concurrency,
    }
    if body.schedule_config:
        orchestrator_metadata["schedule_config"] = body.schedule_config.model_dump()
    if body.circuit_breaker:
        orchestrator_metadata["circuit_breaker"] = body.circuit_breaker.model_dump()

    retry_config = (
        body.retry_config.model_dump()
        if body.retry_config
        else dict(DEFAULT_CAMPAIGN_RETRY_CONFIG)
    )

    doc = repo.create_campaign(
        {
            "org_id": org_id,
            "name": body.name,
            "agent_id": body.agent_id,
            "source_type": body.source_type,
            "source_id": body.source_id,
            "rate_limit_per_second": body.rate_limit_per_second,
            "retry_config": retry_config,
            "orchestrator_metadata": orchestrator_metadata,
            "from_number": body.from_number,
            "created_by": current_user.get("email"),
        }
    )
    return _to_campaign_response(doc)


@router.get("/", response_model=list[CampaignResponse])
async def list_campaigns(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[CampaignResponse]:
    org_id = _require_org(current_user)
    return [_to_campaign_response(c) for c in repo.list_campaigns(org_id)]


@router.get("/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> CampaignResponse:
    org_id = _require_org(current_user)
    try:
        doc = repo.get_campaign_for_org(org_id, campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _to_campaign_response(doc)


@router.delete("/{campaign_id}", response_model=SuccessResponse)
async def delete_campaign(
    campaign_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> SuccessResponse:
    """Delete a campaign (admin / super_admin only)."""
    _require_delete_role(current_user)
    org_id = _require_org(current_user)
    try:
        repo.get_campaign_for_org(org_id, campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    repo.delete_queued_runs_for_campaign(campaign_id)
    repo.delete_campaign(campaign_id)
    return SuccessResponse(message=f"Campaign deleted: {campaign_id}")


@router.post("/{campaign_id}/start")
async def start_campaign(
    campaign_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    org_id = _require_org(current_user)
    try:
        repo.get_campaign_for_org(org_id, campaign_id)
        await campaign_runner_service.start_campaign(campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "started", "campaign_id": campaign_id}


@router.post("/{campaign_id}/pause")
async def pause_campaign(
    campaign_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    org_id = _require_org(current_user)
    try:
        repo.get_campaign_for_org(org_id, campaign_id)
        await campaign_runner_service.pause_campaign(campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "paused", "campaign_id": campaign_id}


@router.post("/{campaign_id}/resume")
async def resume_campaign(
    campaign_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    org_id = _require_org(current_user)
    try:
        repo.get_campaign_for_org(org_id, campaign_id)
        await campaign_runner_service.resume_campaign(campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "resumed", "campaign_id": campaign_id}


@router.patch("/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: str,
    body: UpdateCampaignRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> CampaignResponse:
    org_id = _require_org(current_user)
    try:
        doc = repo.get_campaign_for_org(org_id, campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    patch: dict[str, Any] = {}
    if body.name is not None:
        patch["name"] = body.name
    if body.rate_limit_per_second is not None:
        patch["rate_limit_per_second"] = body.rate_limit_per_second
    metadata = dict(doc.get("orchestrator_metadata") or {})
    if body.max_concurrency is not None:
        _validate_max_concurrency(org_id, str(doc["agent_id"]), body.max_concurrency)
        metadata["max_concurrency"] = body.max_concurrency
    if body.schedule_config is not None:
        metadata["schedule_config"] = body.schedule_config.model_dump()
    if body.circuit_breaker is not None:
        metadata["circuit_breaker"] = body.circuit_breaker.model_dump()
    if metadata != doc.get("orchestrator_metadata"):
        patch["orchestrator_metadata"] = metadata
    if body.retry_config is not None:
        patch["retry_config"] = body.retry_config.model_dump()

    if patch:
        updated = repo.update_campaign(campaign_id, **patch)
        doc = updated or doc
    return _to_campaign_response(doc)


@router.get("/{campaign_id}/runs")
async def get_campaign_runs(
    campaign_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    org_id = _require_org(current_user)
    try:
        repo.get_campaign_for_org(org_id, campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    logs = list_call_logs_by_campaign(org_id, campaign_id, limit=limit, offset=offset)
    return [transform_call_log_urls(log) for log in logs]


@router.get("/{campaign_id}/progress", response_model=CampaignProgressResponse)
async def get_campaign_progress(
    campaign_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> CampaignProgressResponse:
    org_id = _require_org(current_user)
    try:
        repo.get_campaign_for_org(org_id, campaign_id)
        status_doc = await campaign_runner_service.get_campaign_status(campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return CampaignProgressResponse(**status_doc)


@router.post("/{campaign_id}/redial", response_model=CampaignResponse, status_code=201)
async def redial_campaign(
    campaign_id: str,
    body: RedialCampaignRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> CampaignResponse:
    org_id = _require_org(current_user)
    try:
        parent = repo.get_campaign_for_org(org_id, campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    candidates = repo.get_redial_candidates(campaign_id)
    if not candidates:
        raise HTTPException(status_code=400, detail="No failed contacts to redial")

    metadata = dict(parent.get("orchestrator_metadata") or {})
    metadata["parent_campaign_id"] = campaign_id

    child = repo.create_campaign(
        {
            "org_id": org_id,
            "name": body.name,
            "agent_id": parent["agent_id"],
            "source_type": parent.get("source_type", "csv"),
            "source_id": parent["source_id"],
            "rate_limit_per_second": parent.get("rate_limit_per_second", 1),
            "retry_config": parent.get("retry_config"),
            "orchestrator_metadata": metadata,
            "from_number": parent.get("from_number"),
            "created_by": current_user.get("email"),
        }
    )
    child_id = str(child["campaign_id"])
    runs = []
    for idx, candidate in enumerate(candidates, 1):
        ctx = dict(candidate.get("context_variables") or {})
        runs.append(
            {
                "campaign_id": child_id,
                "source_uuid": f"redial_{campaign_id}_{idx}",
                "context_variables": ctx,
                "state": "queued",
            }
        )
    repo.bulk_create_queued_runs(runs)
    repo.update_campaign(child_id, total_rows=len(runs))
    return _to_campaign_response(repo.get_campaign_by_id(child_id) or child)


@router.get("/{campaign_id}/source-download-url")
async def source_download_url(
    campaign_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, str]:
    org_id = _require_org(current_user)
    try:
        doc = repo.get_campaign_for_org(org_id, campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    storage = MinIOStorage()
    url = storage.presigned_get_url(str(doc["source_id"]))
    return {"download_url": url}


@router.get("/{campaign_id}/report")
async def campaign_report(
    campaign_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> StreamingResponse:
    org_id = _require_org(current_user)
    try:
        repo.get_campaign_for_org(org_id, campaign_id)
    except CampaignNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    logs = list_call_logs_by_campaign(org_id, campaign_id, limit=500, offset=0)

    def generate():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "call_id",
                "to_number",
                "status",
                "call_response",
                "duration",
                "created_at",
            ]
        )
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        for log in logs:
            writer.writerow(
                [
                    log.get("call_id"),
                    log.get("to_number"),
                    log.get("status"),
                    log.get("call_response"),
                    log.get("duration"),
                    log.get("created_at"),
                ]
            )
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="campaign_{campaign_id}.csv"'
        },
    )


@router.post("/internal/call-status")
async def internal_call_status(
    body: CampaignCallStatusRequest,
    _: bool = Depends(verify_api_key),
) -> dict[str, str]:
    from app.services.call_log_service import get_call_log, CallLogNotFoundError

    try:
        call_log = get_call_log(body.org_id, body.call_id)
    except CallLogNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await handle_call_terminal(
        call_id=body.call_id,
        campaign_id=call_log.get("campaign_id"),
        queued_run_id=call_log.get("queued_run_id"),
        call_response=body.call_response or call_log.get("call_response"),
    )
    return {"status": "ok"}
