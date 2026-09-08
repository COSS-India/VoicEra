"use client";

import { useCallback, useEffect, useState } from "react";
import { deleteKnowledgeDocument, listKnowledgeDocuments, uploadKnowledgeDocument } from "@/lib/api/knowledge";
import type { KnowledgeDocumentItem } from "@/lib/api-types";

const POLL_INTERVAL_MS = 4000;

export function useKnowledgeBase(onNotify: (title: string, note: string) => void) {
  const [documents, setDocuments] = useState<KnowledgeDocumentItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadError("");
    try {
      const docs = await listKnowledgeDocuments();
      setDocuments(docs);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Couldn't load documents.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Ingestion runs async server-side — poll while anything is still
  // "processing" so status/chunk_count update without a manual refresh.
  const hasProcessing = documents.some((d) => d.status === "processing");
  useEffect(() => {
    if (!hasProcessing) return;
    const id = window.setInterval(load, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [hasProcessing, load]);

  async function upload(file: File): Promise<boolean> {
    setUploading(true);
    try {
      const doc = await uploadKnowledgeDocument(file);
      setDocuments((prev) => [doc, ...prev]);
      onNotify("Upload started", `${doc.original_filename} is being processed.`);
      return true;
    } catch (err) {
      onNotify("Couldn't upload", err instanceof Error ? err.message : "Something went wrong.");
      return false;
    } finally {
      setUploading(false);
    }
  }

  async function remove(doc: KnowledgeDocumentItem) {
    setBusyId(doc.document_id);
    try {
      await deleteKnowledgeDocument(doc.document_id);
      setDocuments((prev) => prev.filter((d) => d.document_id !== doc.document_id));
      onNotify("Deleted", `${doc.original_filename} was removed.`);
    } catch (err) {
      onNotify("Couldn't delete", err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusyId(null);
    }
  }

  return { documents, loading, loadError, uploading, busyId, upload, remove, reload: load };
}
