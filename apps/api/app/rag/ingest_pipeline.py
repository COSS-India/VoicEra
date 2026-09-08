"""PDF bytes -> text -> chunks -> embeddings -> Chroma upsert."""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI

from app.rag.chunk_text import chunk_text
from app.rag.chroma_store import DEFAULT_COLLECTION, upsert_chroma
from app.rag.embed_chunks import embed_openai
from app.rag.pdf_to_text import extract_text_from_pdf

DEFAULT_CHUNK_SIZE = 1000
DEFAULT_OVERLAP = 200
DEFAULT_BATCH_SIZE = 100


class IngestPipelineError(Exception):
    """Raised when ingest cannot complete."""


@dataclass
class IngestResult:
    chunk_id_prefix: str
    filename: str
    characters_extracted: int
    num_chunks: int
    embedding_dim: int
    chroma_dir: str
    collection: str
    embedding_model: str


def ingest_pdf_bytes(
    *,
    pdf_bytes: bytes,
    filename: str,
    chunk_id_prefix: str,
    chroma_dir: Path,
    collection: str = DEFAULT_COLLECTION,
    embedding_model: str,
    openai_api_key: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_OVERLAP,
    dimensions: int | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    org_id: str | None = None,
    document_id: str | None = None,
) -> IngestResult:
    """Full pipeline: PDF bytes -> text -> chunks -> embeddings -> Chroma upsert."""
    if not filename.lower().endswith(".pdf"):
        raise IngestPipelineError("Expected a .pdf file")
    if chunk_size < 1 or chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise IngestPipelineError(
            "Invalid chunk_size / chunk_overlap (overlap must be < chunk_size)"
        )
    if not pdf_bytes:
        raise IngestPipelineError("Empty file")

    api_key = (openai_api_key or "").strip()
    if not api_key:
        raise IngestPipelineError("KB_EMBEDDING_API_KEY is not configured")

    suffix = Path(filename).suffix or ".pdf"
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(pdf_bytes)

        text = extract_text_from_pdf(tmp_path)
        if not text.strip():
            raise IngestPipelineError(
                "No extractable text (empty or image-only PDF)."
            )

        chunks = chunk_text(text, chunk_size, chunk_overlap)
        if not chunks:
            raise IngestPipelineError("Chunking produced no segments")

        client = OpenAI(api_key=api_key)
        embeddings = embed_openai(
            client,
            chunks,
            model=embedding_model,
            batch_size=batch_size,
            dimensions=dimensions,
        )

        n = embeddings.shape[0]
        ids = [f"{chunk_id_prefix}_{i}" for i in range(n)]
        metadatas: list[dict] = []
        for i in range(n):
            meta: dict = {
                "chunk_index": i,
                "chunk_id_prefix": chunk_id_prefix,
                "source_filename": filename,
                "embedding_model": embedding_model,
            }
            if org_id is not None:
                meta["org_id"] = org_id
            if document_id is not None:
                meta["document_id"] = document_id
            metadatas.append(meta)

        upsert_chroma(
            chroma_dir=chroma_dir,
            collection_name=collection,
            embeddings=embeddings,
            texts=chunks,
            ids=ids,
            metadatas=metadatas,
            model_name=embedding_model,
        )

        return IngestResult(
            chunk_id_prefix=chunk_id_prefix,
            filename=filename,
            characters_extracted=len(text),
            num_chunks=n,
            embedding_dim=int(embeddings.shape[1]),
            chroma_dir=str(chroma_dir.resolve()),
            collection=collection,
            embedding_model=embedding_model,
        )
    finally:
        if tmp_path is not None and tmp_path.is_file():
            try:
                tmp_path.unlink()
            except OSError:
                pass
