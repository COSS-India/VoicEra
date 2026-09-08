"""ChromaDB upsert, query, and delete helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

DEFAULT_COLLECTION = "rag_docs"


class ChromaStoreError(Exception):
    """Raised when Chroma operations fail."""


def upsert_chroma(
    *,
    chroma_dir: Path,
    collection_name: str,
    embeddings: np.ndarray,
    texts: list[str],
    ids: list[str],
    metadatas: list[dict[str, Any]],
    model_name: str,
) -> None:
    """Upsert chunk vectors into an org-scoped Chroma collection."""
    import chromadb

    chroma_dir.mkdir(parents=True, exist_ok=True)
    _, dim = embeddings.shape
    client = chromadb.PersistentClient(path=str(chroma_dir.resolve()))
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={
            "hnsw:space": "cosine",
            "embedding_dim": str(dim),
            "embedding_model": model_name,
        },
    )
    collection.upsert(
        ids=ids,
        embeddings=embeddings.tolist(),
        documents=texts,
        metadatas=metadatas,
    )


def delete_chunks_for_document(
    chroma_dir: Path,
    document_id: str,
    collection_name: str = DEFAULT_COLLECTION,
    *,
    raise_on_delete_error: bool = False,
) -> None:
    """Remove all vectors for a knowledge document from Chroma."""
    doc_id = (document_id or "").strip()
    if not doc_id:
        return
    path = Path(chroma_dir).resolve()
    if not path.is_dir():
        return

    import chromadb

    try:
        client = chromadb.PersistentClient(path=str(path))
        collection = client.get_collection(name=collection_name)
    except Exception:
        return

    wheres: list[dict[str, Any]] = [
        {"$or": [{"document_id": doc_id}, {"chunk_id_prefix": doc_id}]},
        {"document_id": doc_id},
        {"chunk_id_prefix": doc_id},
    ]
    last_err: BaseException | None = None
    for where in wheres:
        try:
            collection.delete(where=where)
            return
        except Exception as exc:
            last_err = exc
    if raise_on_delete_error and last_err is not None:
        raise ChromaStoreError(f"Chroma delete failed: {last_err}") from last_err


def query_chroma(
    *,
    chroma_dir: Path,
    query_embedding: list[float],
    collection_name: str = DEFAULT_COLLECTION,
    n_results: int = 5,
    document_ids: list[str] | None = None,
) -> dict[str, Any]:
    """ANN query against org-scoped Chroma; returns raw Chroma query dict."""
    import chromadb

    path = Path(chroma_dir).resolve()
    if not path.is_dir():
        return {"ids": [[]], "documents": [[]], "distances": [[]], "metadatas": [[]]}

    try:
        client = chromadb.PersistentClient(path=str(path))
        collection = client.get_collection(name=collection_name)
    except Exception:
        return {"ids": [[]], "documents": [[]], "distances": [[]], "metadatas": [[]]}

    include = ["documents", "distances", "metadatas"]
    where = {"document_id": {"$in": document_ids}} if document_ids else None
    try:
        if where:
            return collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results,
                include=include,
                where=where,
            )
        return collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=include,
        )
    except Exception:
        return collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=include,
        )
