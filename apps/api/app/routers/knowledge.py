"""Knowledge base API: org-scoped PDF upload and ingest status."""

from __future__ import annotations

from typing import Any, Iterator

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse

from app.auth import get_current_user
from app.config import settings
from app.models.schemas import (
    KnowledgeDeleteResponse,
    KnowledgeDocumentResponse,
    KnowledgeUploadResponse,
)
from app.services import knowledge_service
from app.storage.minio_client import MinIOStorage

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


def _stream_minio_object(bucket_name: str, object_name: str, content_type: str) -> StreamingResponse:
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


@router.get("", response_model=list[KnowledgeDocumentResponse])
async def list_knowledge_documents(
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """List all knowledge PDFs for the authenticated user's organization."""
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization",
        )
    return knowledge_service.list_documents(org_id)


@router.get("/{document_id}/preview")
async def preview_knowledge_document(
    document_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> StreamingResponse:
    """Stream the original PDF from MinIO so the frontend can render it inline."""
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization",
        )

    doc = knowledge_service.get_document(org_id, document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    storage_key = doc.get("storage_key")
    if not storage_key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview not available for this document")

    storage = MinIOStorage()
    if not storage.object_exists(settings.MINIO_BUCKET, storage_key):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    return _stream_minio_object(settings.MINIO_BUCKET, storage_key, "application/pdf")


@router.post(
    "/upload",
    response_model=KnowledgeUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_knowledge_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> KnowledgeUploadResponse:
    """Upload a PDF and schedule background ingest into org-scoped Chroma."""
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization",
        )

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are allowed",
        )

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty file",
        )
    if len(content) > settings.KB_MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"File too large (max {settings.KB_MAX_UPLOAD_BYTES // (1024 * 1024)} MB)"
            ),
        )

    document_id = knowledge_service.create_document_pending(org_id, file.filename)
    try:
        storage_key = knowledge_service.upload_pdf_to_minio(
            org_id,
            document_id,
            file.filename,
            content,
        )
        knowledge_service.update_document(
            document_id,
            org_id,
            status="processing",
            storage_key=storage_key,
        )
    except Exception as exc:
        knowledge_service.update_document(
            document_id,
            org_id,
            status="failed",
            error_message=f"Failed to store upload: {exc}",
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to store uploaded file",
        ) from exc

    background_tasks.add_task(
        knowledge_service.run_ingest_job,
        document_id,
        org_id,
        file.filename,
        content,
    )

    return KnowledgeUploadResponse(
        document_id=document_id,
        org_id=org_id,
        original_filename=file.filename,
        status="processing",
    )


@router.delete(
    "/{document_id}",
    response_model=KnowledgeDeleteResponse,
    status_code=status.HTTP_200_OK,
)
async def delete_knowledge_document(
    document_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> KnowledgeDeleteResponse:
    """Delete a knowledge document and its Chroma vectors for the user's organization."""
    org_id = current_user.get("org_id")
    if not org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization",
        )
    try:
        knowledge_service.delete_knowledge_document(org_id, document_id)
    except knowledge_service.KnowledgeDocumentNotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        ) from None
    except knowledge_service.KnowledgeChromaDeleteError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=exc.message,
        ) from exc
    return KnowledgeDeleteResponse(deleted=True)
