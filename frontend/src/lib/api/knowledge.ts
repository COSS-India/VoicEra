import { apiFetch, apiFetchBlob } from "@/lib/api/http";
import type { KnowledgeDocumentItem } from "@/lib/api-types";

export async function listKnowledgeDocuments(): Promise<KnowledgeDocumentItem[]> {
  return apiFetch<KnowledgeDocumentItem[]>("/knowledge");
}

/** The original PDF, streamed from MinIO — 404s when the document has no
 * stored file (e.g. never finished uploading). */
export async function previewKnowledgeDocument(documentId: string): Promise<Blob> {
  return apiFetchBlob(`/knowledge/${encodeURIComponent(documentId)}/preview`);
}

/** PDF only, up to the backend's KB_MAX_UPLOAD_BYTES (25MB) — returns the new
 * document immediately with status "processing"; ingestion runs async server-side. */
export async function uploadKnowledgeDocument(file: File): Promise<KnowledgeDocumentItem> {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetch<KnowledgeDocumentItem>("/knowledge/upload", {
    method: "POST",
    body: formData,
  });
}

export async function deleteKnowledgeDocument(documentId: string): Promise<{ deleted: boolean }> {
  return apiFetch<{ deleted: boolean }>(`/knowledge/${encodeURIComponent(documentId)}`, {
    method: "DELETE",
  });
}
