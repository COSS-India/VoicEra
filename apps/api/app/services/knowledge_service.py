"""
Knowledge base: org-scoped PDF metadata in Mongo + ingest to Chroma.
"""

from __future__ import annotations

import hashlib
import io
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

from app.config import settings
from app.database import get_database
from app.rag.chroma_store import DEFAULT_COLLECTION, delete_chunks_for_document, query_chroma
from app.rag.ingest_pipeline import IngestPipelineError, ingest_pdf_bytes

logger = logging.getLogger(__name__)

COLLECTION_NAME = "KnowledgeDocuments"


class KnowledgeDocumentNotFoundError(Exception):
    """No KnowledgeDocuments row for this org and document_id."""


class KnowledgeChromaDeleteError(Exception):
    """Chroma delete failed; Mongo row was not removed."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class KnowledgeRetrievalError(Exception):
    """Knowledge retrieval failed for the current query."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class KnowledgeDocumentNotReadyError(Exception):
    """Referenced knowledge documents are missing or not ready."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _org_chroma_subdir(org_id: str) -> str:
    return hashlib.sha256(org_id.encode("utf-8")).hexdigest()[:48]


def chroma_dir_for_org(org_id: str) -> Path:
    base = Path(settings.CHROMA_BASE_DIR)
    if not base.is_absolute():
        base = Path(__file__).resolve().parent.parent / base
    return base / "orgs" / _org_chroma_subdir(org_id)


def kb_storage_key(org_id: str, document_id: str, filename: str) -> str:
    safe_name = Path(filename).name or "document.pdf"
    return f"knowledge/{org_id}/{document_id}/{safe_name}"


def _embedding_api_key() -> str:
    return (settings.KB_EMBEDDING_API_KEY or "").strip()


def _user_friendly_ingest_error(exc: BaseException) -> str:
    if isinstance(exc, IngestPipelineError):
        return str(exc)[:2000]

    raw = str(exc).strip()
    lower = raw.lower()
    if any(
        token in lower
        for token in (
            "429",
            "quota",
            "rate limit",
            "rate_limit",
            "exceeded your current quota",
            "insufficient_quota",
        )
    ):
        return (
            "Embedding usage limit reached. Check your OpenAI billing or plan, "
            "then try uploading again."
        )
    if any(
        token in lower
        for token in (
            "401",
            "invalid api key",
            "incorrect api key",
            "authentication",
            "invalid_api_key",
        )
    ):
        return "The embedding API key is not valid. Update KB_EMBEDDING_API_KEY and retry."

    logger.warning("Knowledge ingest error (sanitized for user): %s", raw)
    return "We couldn't process this file. Please try again later."


def create_document_pending(
    org_id: str,
    original_filename: str,
    *,
    storage_key: str | None = None,
) -> str:
    """Insert Mongo row with status processing; return document_id."""
    db = get_database()
    table = db[COLLECTION_NAME]
    document_id = str(uuid.uuid4())
    now = _now_iso()
    table.insert_one(
        {
            "document_id": document_id,
            "org_id": org_id,
            "original_filename": original_filename,
            "status": "processing",
            "chunk_count": None,
            "embedding_model": None,
            "storage_key": storage_key,
            "error_message": None,
            "created_at": now,
            "updated_at": now,
        }
    )
    return document_id


def update_document(
    document_id: str,
    org_id: str,
    *,
    status: str,
    chunk_count: int | None = None,
    embedding_model: str | None = None,
    storage_key: str | None = None,
    error_message: str | None = None,
) -> None:
    db = get_database()
    table = db[COLLECTION_NAME]
    now = _now_iso()
    update: dict[str, Any] = {
        "status": status,
        "updated_at": now,
    }
    if chunk_count is not None:
        update["chunk_count"] = chunk_count
    if embedding_model is not None:
        update["embedding_model"] = embedding_model
    if storage_key is not None:
        update["storage_key"] = storage_key
    if error_message is not None:
        update["error_message"] = error_message
    elif status == "ready":
        update["error_message"] = None

    table.update_one(
        {"document_id": document_id, "org_id": org_id},
        {"$set": update},
    )


def list_documents(org_id: str) -> list[dict[str, Any]]:
    db = get_database()
    table = db[COLLECTION_NAME]
    cursor = table.find({"org_id": org_id}).sort("created_at", -1)
    out: list[dict[str, Any]] = []
    for doc in cursor:
        doc.pop("_id", None)
        out.append(doc)
    return out


def get_document(org_id: str, document_id: str) -> dict[str, Any] | None:
    db = get_database()
    table = db[COLLECTION_NAME]
    doc = table.find_one({"document_id": document_id, "org_id": org_id})
    if not doc:
        return None
    doc.pop("_id", None)
    return doc


def assert_documents_ready(org_id: str, document_ids: list[str]) -> None:
    """Ensure every document exists for the org and has status ready."""
    if not document_ids:
        raise KnowledgeDocumentNotReadyError(
            "knowledge_base.document_ids must be non-empty when enabled"
        )
    db = get_database()
    table = db[COLLECTION_NAME]
    missing: list[str] = []
    not_ready: list[str] = []
    for doc_id in document_ids:
        row = table.find_one({"document_id": doc_id, "org_id": org_id})
        if not row:
            missing.append(doc_id)
            continue
        if row.get("status") != "ready":
            not_ready.append(doc_id)
    if missing:
        raise KnowledgeDocumentNotReadyError(
            "Unknown knowledge_base.document_ids for this organization: "
            + ", ".join(missing)
        )
    if not_ready:
        raise KnowledgeDocumentNotReadyError(
            "Knowledge documents are not ready (still processing or failed): "
            + ", ".join(not_ready)
        )


def retrieve_chunks_for_query(
    *,
    org_id: str,
    question: str,
    document_ids: list[str] | None = None,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Retrieve top-k relevant chunk texts from org-scoped Chroma."""
    query = (question or "").strip()
    if not query:
        return []

    if document_ids is not None and len(document_ids) == 0:
        return []

    api_key = _embedding_api_key()
    if not api_key:
        raise KnowledgeRetrievalError("KB_EMBEDDING_API_KEY is not configured")

    k = max(1, min(int(top_k or 5), 10))
    selected_ids = [d.strip() for d in (document_ids or []) if d and d.strip()]
    chroma_dir = chroma_dir_for_org(org_id)
    if not chroma_dir.is_dir():
        return []

    client = OpenAI(api_key=api_key)
    try:
        emb_resp = client.embeddings.create(
            model=settings.KB_EMBEDDING_MODEL,
            input=query,
        )
        q_emb = list(emb_resp.data[0].embedding)
    except Exception as exc:
        raise KnowledgeRetrievalError(f"Embedding failed: {exc}") from exc

    n_results = max(k, min(25, k * 4 if selected_ids else k))
    results = query_chroma(
        chroma_dir=chroma_dir,
        query_embedding=q_emb,
        collection_name=DEFAULT_COLLECTION,
        n_results=n_results,
        document_ids=selected_ids or None,
    )

    ids_batch = results.get("ids") or []
    docs_batch = results.get("documents") or []
    dists_batch = results.get("distances") or []
    metas_batch = results.get("metadatas") or []
    if not ids_batch or not ids_batch[0]:
        return []

    ids = ids_batch[0]
    docs = docs_batch[0] if docs_batch else []
    dists = dists_batch[0] if dists_batch else [None] * len(ids)
    metas = metas_batch[0] if metas_batch else [None] * len(ids)
    out: list[dict[str, Any]] = []
    for cid, doc, dist, meta in zip(ids, docs, dists, metas, strict=False):
        metadata = meta or {}
        doc_id = metadata.get("document_id") or metadata.get("chunk_id_prefix")
        if selected_ids and doc_id not in selected_ids:
            continue
        text = (doc or "").strip()
        if not text:
            continue
        out.append(
            {
                "chunk_id": cid,
                "document_id": doc_id,
                "source_filename": metadata.get("source_filename"),
                "text": text,
                "distance": dist,
            }
        )
        if len(out) >= k:
            break
    return out


def _delete_chroma_vectors(org_id: str, document_id: str) -> None:
    chroma_dir = chroma_dir_for_org(org_id)
    try:
        delete_chunks_for_document(
            chroma_dir,
            document_id,
            collection_name=DEFAULT_COLLECTION,
            raise_on_delete_error=True,
        )
    except Exception as exc:
        from app.rag.chroma_store import ChromaStoreError

        if isinstance(exc, ChromaStoreError):
            raise KnowledgeChromaDeleteError(str(exc)) from exc
        raise KnowledgeChromaDeleteError(str(exc)) from exc


def _delete_minio_object(storage_key: str | None) -> None:
    if not storage_key:
        return
    try:
        from app.storage.minio_client import MinIOStorage

        storage = MinIOStorage()
        storage.client.remove_object(settings.MINIO_BUCKET, storage_key)
    except Exception as exc:
        logger.warning("Failed to delete KB object %s: %s", storage_key, exc)


def delete_knowledge_document(org_id: str, document_id: str) -> None:
    """Remove Chroma vectors and MinIO object, then delete the Mongo row."""
    existing = get_document(org_id, document_id)
    if not existing:
        raise KnowledgeDocumentNotFoundError()

    _delete_chroma_vectors(org_id, document_id)
    _delete_minio_object(existing.get("storage_key"))

    db = get_database()
    deleted = db[COLLECTION_NAME].delete_one(
        {"document_id": document_id, "org_id": org_id}
    )
    if deleted.deleted_count == 0:
        raise KnowledgeDocumentNotFoundError()


def upload_pdf_to_minio(org_id: str, document_id: str, filename: str, data: bytes) -> str:
    """Store the original PDF in MinIO; return object key."""
    from app.storage.minio_client import MinIOStorage

    key = kb_storage_key(org_id, document_id, filename)
    storage = MinIOStorage()
    storage.client.put_object(
        settings.MINIO_BUCKET,
        key,
        io.BytesIO(data),
        length=len(data),
        content_type="application/pdf",
    )
    return key


def run_ingest_job(
    document_id: str,
    org_id: str,
    original_filename: str,
    pdf_bytes: bytes,
) -> None:
    """Background task: embed PDF into org Chroma and update Mongo."""
    api_key = _embedding_api_key()
    if not api_key:
        update_document(
            document_id,
            org_id,
            status="failed",
            error_message="KB_EMBEDDING_API_KEY is not configured.",
        )
        return

    chroma_dir = chroma_dir_for_org(org_id)
    try:
        result = ingest_pdf_bytes(
            pdf_bytes=pdf_bytes,
            filename=original_filename,
            chunk_id_prefix=document_id,
            chroma_dir=chroma_dir,
            collection=DEFAULT_COLLECTION,
            embedding_model=settings.KB_EMBEDDING_MODEL,
            openai_api_key=api_key,
            org_id=org_id,
            document_id=document_id,
        )
        update_document(
            document_id,
            org_id,
            status="ready",
            chunk_count=result.num_chunks,
            embedding_model=result.embedding_model,
        )
        logger.info(
            "Knowledge ingest ready document_id=%s org_id=%s chunks=%s",
            document_id,
            org_id,
            result.num_chunks,
        )
    except IngestPipelineError as exc:
        logger.warning("Knowledge ingest failed: %s", exc)
        update_document(
            document_id,
            org_id,
            status="failed",
            error_message=_user_friendly_ingest_error(exc),
        )
    except Exception as exc:
        logger.exception("Knowledge ingest unexpected error")
        update_document(
            document_id,
            org_id,
            status="failed",
            error_message=_user_friendly_ingest_error(exc),
        )
