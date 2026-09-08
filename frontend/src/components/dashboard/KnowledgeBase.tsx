"use client";

import { useEffect, useMemo, useState } from "react";
import { Search, Upload } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { Spinner } from "@/components/ui/Spinner";
import { UploadDocumentDialog } from "@/components/knowledge/UploadDocumentDialog";
import { FileCardGrid, type KnowledgeFile } from "@/components/knowledge/FileCard";
import { PdfPreviewSheet } from "@/components/knowledge/PdfPreviewSheet";
import { useKnowledgeBase } from "@/hooks/useKnowledgeBase";
import { listAgents } from "@/lib/api-client";
import { previewKnowledgeDocument } from "@/lib/api/knowledge";
import { formatDateTime } from "@/lib/format";
import type { AgentApiResponse, KnowledgeDocumentItem } from "@/lib/api-types";

function toKnowledgeFile(doc: KnowledgeDocumentItem): KnowledgeFile {
  return {
    id: doc.document_id,
    name: doc.original_filename,
    status: doc.status === "failed" ? "error" : doc.status,
    passages: doc.chunk_count ?? 0,
    addedAt: formatDateTime(doc.created_at),
  };
}

export function KnowledgeBase({ onNotify }: { onNotify: (title: string, note: string) => void }) {
  const { documents, loading, loadError, uploading, upload, remove } = useKnowledgeBase(onNotify);
  const [query, setQuery] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [previewFile, setPreviewFile] = useState<KnowledgeFile | null>(null);
  const [agents, setAgents] = useState<AgentApiResponse[]>([]);
  const [agentFilterId, setAgentFilterId] = useState("");

  useEffect(() => {
    let cancelled = false;
    listAgents()
      .then((data) => {
        if (!cancelled) setAgents(data);
      })
      .catch(() => {
        /* filter just falls back to unavailable */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // A document doesn't know which agents use it — only agents record which
  // document IDs they attach — so invert that into document_id -> agents here.
  const agentsByDocumentId = useMemo(() => {
    const map: Record<string, AgentApiResponse[]> = {};
    for (const a of agents) {
      for (const docId of a.config.knowledge_base.document_ids) {
        (map[docId] ??= []).push(a);
      }
    }
    return map;
  }, [agents]);

  const agentsWithDocuments = useMemo(
    () => agents.filter((a) => a.config.knowledge_base.document_ids.length > 0),
    [agents],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return documents.filter((d) => {
      if (q && !d.original_filename.toLowerCase().includes(q)) return false;
      if (agentFilterId && !agentsByDocumentId[d.document_id]?.some((a) => a.agent_id === agentFilterId)) {
        return false;
      }
      return true;
    });
  }, [documents, query, agentFilterId, agentsByDocumentId]);

  const files = useMemo(() => filtered.map(toKnowledgeFile), [filtered]);
  const documentsById = useMemo(
    () => Object.fromEntries(documents.map((d) => [d.document_id, d])),
    [documents],
  );

  async function handlePreview(file: KnowledgeFile) {
    try {
      const blob = await previewKnowledgeDocument(file.id);
      setPreviewFile({ ...file, blob });
    } catch (err) {
      onNotify("Couldn't load preview", err instanceof Error ? err.message : "Something went wrong.");
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-v-line pb-6">
        <div className="flex flex-col gap-1.5">
          <h1 className="text-3xl font-semibold tracking-tight">Knowledge Base</h1>
          <p className="max-w-[62ch] text-sm font-light leading-relaxed text-v-muted">
            Documents here are searched at call time, so agents quote them instead of guessing.
          </p>
        </div>
        <Button onClick={() => setUploadOpen(true)}>
          <Upload className="size-4" strokeWidth={1.75} />
          Upload document
        </Button>
      </div>

      {loadError ? (
        <div className="rounded-v-md border border-v-danger-line bg-v-danger-pale px-4 py-3 text-sm text-v-danger">
          {loadError}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2.5 rounded-v-md border border-v-line bg-v-soft/40 p-2.5">
        <div className="relative min-w-56 flex-1">
          <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-v-muted" />
          <input
            type="search"
            placeholder="Search documents"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full rounded-v-lg border border-v-line-strong bg-white py-3 pl-11 pr-4 text-[13.5px] text-v-fg transition-colors duration-[120ms] focus:border-v-accent"
          />
        </div>
        {agentsWithDocuments.length > 0 ? (
          <div className="flex shrink-0 items-center gap-2">
            <span className="text-[13px] font-medium text-v-body">Agent</span>
            <Select
              size="sm"
              aria-label="Filter by agent"
              className="!h-9 !py-0"
              value={agentFilterId}
              onChange={(e) => setAgentFilterId(e.target.value)}
            >
              <option value="">All agents</option>
              {agentsWithDocuments.map((a) => (
                <option key={a.agent_id} value={a.agent_id}>
                  {a.name}
                </option>
              ))}
            </Select>
          </div>
        ) : null}
        <span className="ml-auto font-mono text-[10px] uppercase tracking-[.14em] text-v-muted">
          {filtered.length} shown
        </span>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-v-muted">
          <Spinner light={false} /> Loading documents…
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center gap-1 rounded-v-md border border-dashed border-v-line bg-white p-12 text-center">
          <span className="text-sm font-semibold">
            {query || agentFilterId ? "Nothing matches" : "No documents yet"}
          </span>
          <span className="text-xs font-light text-v-muted">
            {query || agentFilterId ? "Try another search or agent." : "Upload a PDF to start grounding your agents."}
          </span>
        </div>
      ) : (
        <FileCardGrid
          files={files}
          onPreview={handlePreview}
          onDelete={(file) => {
            const doc = documentsById[file.id];
            if (doc) remove(doc);
          }}
        />
      )}

      <UploadDocumentDialog open={uploadOpen} uploading={uploading} onUpload={upload} onClose={() => setUploadOpen(false)} />

      <PdfPreviewSheet file={previewFile} onClose={() => setPreviewFile(null)} />
    </div>
  );
}
