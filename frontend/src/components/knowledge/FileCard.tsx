"use client";

import { useEffect, useRef, useState } from "react";
import { Eye, FileText, Trash2, X } from "lucide-react";

export interface KnowledgeFile {
  id: string;
  name: string;
  status: "ready" | "processing" | "error";
  passages: number;
  addedAt: string;
  /** PDF file blob or a URL pointing at one — undefined when no preview source exists yet. */
  blob?: Blob | string;
}

const STATUS_META: Record<KnowledgeFile["status"], { label: string; fg: string; bg: string }> = {
  ready: { label: "Ready", fg: "#2F6B4F", bg: "#E5F1E9" },
  processing: { label: "Processing", fg: "#B08A2E", bg: "#FBF3DF" },
  error: { label: "Couldn't process", fg: "#B3483A", bg: "#FBEAE7" },
};

/** Grace period before a confirmed delete actually fires — long enough to
 * read and tap "Undo," short enough that the placeholder isn't a fixture. */
const UNDO_WINDOW_MS = 5000;

type DeleteStage = "idle" | "confirm" | "pending";

/** Grid-friendly card for one ingested document. Never renders or knows about
 * a preview surface — it only ever reports the click via `onPreview`; the
 * parent owns whatever preview UI (if any) responds to it. */
export function FileCard({
  file,
  onDelete,
  onPreview,
}: {
  file: KnowledgeFile;
  onDelete: (file: KnowledgeFile) => void;
  onPreview: (file: KnowledgeFile) => void;
}) {
  const [stage, setStage] = useState<DeleteStage>("idle");
  const timeoutRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timeoutRef.current) window.clearTimeout(timeoutRef.current);
    };
  }, []);

  function requestDelete() {
    setStage("pending");
    timeoutRef.current = window.setTimeout(() => {
      timeoutRef.current = null;
      onDelete(file);
    }, UNDO_WINDOW_MS);
  }

  function undo() {
    if (timeoutRef.current) {
      window.clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    setStage("idle");
  }

  if (stage === "pending") {
    return (
      <div className="flex items-center justify-between gap-3 rounded-lg border border-dashed border-[#E3E0D6] bg-white px-4.5 py-4">
        <span className="truncate text-[13.5px] font-light text-[#7A7669]">
          <span className="font-medium text-[#20201C]">{file.name}</span> was removed
        </span>
        <button
          type="button"
          onClick={undo}
          className="shrink-0 cursor-pointer text-[13px] font-semibold text-[#20201C] underline underline-offset-2 hover:text-[#7A7669]"
        >
          Undo
        </button>
      </div>
    );
  }

  const status = STATUS_META[file.status];

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-[#E3E0D6] bg-white p-4.5">
      <div className="flex items-start justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2.5">
          <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-[#F3F1EA] text-[#7A7669]">
            <FileText className="size-4" strokeWidth={1.75} />
          </span>
          <span className="min-w-0 truncate text-[15px] font-medium text-[#20201C]" title={file.name}>
            {file.name}
          </span>
        </span>

        <span className="flex shrink-0 items-center">
          {stage === "confirm" ? (
            <span className="flex items-center gap-1 whitespace-nowrap pl-1 text-[13px] font-medium text-[#20201C]">
              Delete?
              <button
                type="button"
                onClick={requestDelete}
                className="cursor-pointer rounded-md px-1.5 py-1 font-semibold text-[#B3483A] hover:bg-[#FBEAE7]"
              >
                Yes
              </button>
              <button
                type="button"
                aria-label="Cancel delete"
                onClick={() => setStage("idle")}
                className="flex size-8 cursor-pointer items-center justify-center rounded-full text-[#7A7669] hover:bg-[#F3F1EA]"
              >
                <X className="size-3.5" strokeWidth={1.9} />
              </button>
            </span>
          ) : (
            <>
              <button
                type="button"
                aria-label="Preview document"
                onClick={() => onPreview(file)}
                className="flex size-11 shrink-0 cursor-pointer items-center justify-center rounded-md text-[#7A7669] transition-colors hover:bg-[#F3F1EA] hover:text-[#20201C]"
              >
                <Eye className="size-4" strokeWidth={1.75} />
              </button>
              <button
                type="button"
                aria-label="Delete document"
                onClick={() => setStage("confirm")}
                className="flex size-11 shrink-0 cursor-pointer items-center justify-center rounded-md text-[#7A7669] transition-colors hover:bg-[#FBEAE7] hover:text-[#B3483A]"
              >
                <Trash2 className="size-4" strokeWidth={1.75} />
              </button>
            </>
          )}
        </span>
      </div>

      <span className="flex w-fit items-center gap-1.5 text-[13px] font-medium" style={{ color: status.fg }}>
        <span className="size-1.5 shrink-0 rounded-full" style={{ background: status.fg }} />
        {status.label}
      </span>

      <div className="flex items-center justify-between gap-2 border-t border-[#EDEBE2] pt-3 font-mono text-[12.5px] text-[#7A7669]">
        <span>{file.status === "ready" ? `${file.passages} passages` : "—"}</span>
        <span>{file.addedAt}</span>
      </div>
    </div>
  );
}

/** Responsive document-library grid: auto-fill, minmax(280px, 1fr), 16px gap. */
export function FileCardGrid({
  files,
  onDelete,
  onPreview,
}: {
  files: KnowledgeFile[];
  onDelete: (file: KnowledgeFile) => void;
  onPreview: (file: KnowledgeFile) => void;
}) {
  return (
    <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))" }}>
      {files.map((f) => (
        <FileCard key={f.id} file={f} onDelete={onDelete} onPreview={onPreview} />
      ))}
    </div>
  );
}
