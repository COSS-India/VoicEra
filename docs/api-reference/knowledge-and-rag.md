---
title: Knowledge and RAG
description: Upload documents and retrieve grounded context.
---

## Knowledge

`apps/api/app/routers/knowledge.py`, prefix `/api/v1/knowledge`. See [Knowledge base (RAG)](../guides/concepts/knowledge-base-rag).

### `GET /knowledge`

Bearer. Array of `KnowledgeDocumentResponse`: `document_id`, `org_id`, `original_filename`, `status`, `chunk_count`, `embedding_model`, `storage_key`, `error_message`, `created_at`, `updated_at`.

### `POST /knowledge/upload`

Bearer. `201`. `multipart/form-data` with one `file` field.

```bash
curl -X POST http://localhost:8000/api/v1/knowledge/upload \
  -H "Authorization: Bearer YOUR_JWT" \
  -F "file=@handbook.pdf"
```

PDF only, non-empty, under `KB_MAX_UPLOAD_BYTES`. The file is stored in MinIO and ingest is scheduled as a FastAPI background task, so the response comes back immediately:

```json
{
  "document_id": "…",
  "org_id": "…",
  "original_filename": "handbook.pdf",
  "status": "processing"
}
```

Poll `GET /knowledge` until `status` is `ready`. An agent cannot reference a document that is not `ready` — the agent config validator rejects it. Failure codes: `400` for a non-PDF or empty file, `413` for oversize, `500` when the object store write fails (the document is marked `failed`).

### `GET /knowledge/{document_id}/preview`

Bearer. Streams the original PDF straight out of MinIO (`media_type: application/pdf`), so the frontend can render it inline instead of forcing a download. `404` when the document does not exist in your organisation, has no `storage_key`, or the object is missing from MinIO.

### `DELETE /knowledge/{document_id}`

Bearer. Deletes the metadata document and its vectors from the organisation's Chroma store. Returns `{"deleted": true}`. `404` when the document does not exist in your organisation.

## RAG

`apps/api/app/routers/rag.py`, prefix `/api/v1/rag`. One route, for the runtime.

### `POST /rag/retrieve`

`X-API-Key`. Service-to-service chunk retrieval.

```json
{
  "org_id": "…",
  "question": "What is the refund window?",
  "document_ids": ["doc_1", "doc_2"],
  "top_k": 5
}
```

`document_ids` is optional — omitting it searches the whole organisation store. `top_k` defaults to `5` and is bounded `1`–`10`.

Returns `KnowledgeRetrieveResponse`:

```json
{
  "chunks": [
    {
      "chunk_id": "…",
      "document_id": "doc_1",
      "source_filename": "handbook.pdf",
      "text": "Refunds are accepted within 30 days…",
      "distance": 0.21
    }
  ]
}
```

`distance` is the vector distance — lower is closer. A retrieval failure returns `500` with the reason in `detail`.

## Related

* [Endpoints cheatsheet](endpoints-cheatsheet) — every route on one page
* [Authentication](authentication) — tokens, headers, and roles
* [Errors](errors) — status codes and error shapes
