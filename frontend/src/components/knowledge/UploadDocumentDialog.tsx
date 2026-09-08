"use client";

import { useRef, useState } from "react";
import { Upload } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Dialog, DialogHeader } from "@/components/ui/Dialog";
import { Spinner } from "@/components/ui/Spinner";
import { formatBytes } from "@/lib/format";

const MAX_UPLOAD_BYTES = 25 * 1024 * 1024; // matches backend settings.KB_MAX_UPLOAD_BYTES

/** File picker + drag-drop zone for adding a knowledge base document.
 * Validates type/size client-side against the same limits the backend
 * enforces, so a bad file never round-trips. Shared by the Knowledge Base
 * page and the agent-creation wizard's Prompt & knowledge base step, so both
 * upload through the exact same flow. */
export function UploadDocumentDialog({
  open,
  uploading,
  onUpload,
  onClose,
}: {
  open: boolean;
  uploading: boolean;
  onUpload: (file: File) => Promise<boolean>;
  onClose: () => void;
}) {
  const [dragOver, setDragOver] = useState(false);
  const [error, setError] = useState("");
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function validate(file: File): string | null {
    if (!file.name.toLowerCase().endsWith(".pdf")) return "Only PDF files are supported.";
    if (file.size > MAX_UPLOAD_BYTES) return `File is too large (max ${MAX_UPLOAD_BYTES / (1024 * 1024)} MB).`;
    return null;
  }

  function handleFile(file: File) {
    const validationError = validate(file);
    if (validationError) {
      setError(validationError);
      setPendingFile(null);
      return;
    }
    setError("");
    setPendingFile(file);
  }

  async function confirmUpload() {
    if (!pendingFile) return;
    const ok = await onUpload(pendingFile);
    if (ok) {
      setPendingFile(null);
      onClose();
    }
  }

  function handleClose() {
    setPendingFile(null);
    setError("");
    onClose();
  }

  return (
    <Dialog open={open} onClose={handleClose} widthClassName="max-w-md">
      <DialogHeader title="Upload a document" subtitle="PDF only, up to 25 MB." onClose={handleClose} />
      <div className="flex flex-col gap-4 p-5">
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            const file = e.dataTransfer.files[0];
            if (file) handleFile(file);
          }}
          onClick={() => inputRef.current?.click()}
          className={`flex cursor-pointer flex-col items-center gap-2 rounded-v-md border border-dashed p-10 text-center transition-colors ${
            dragOver ? "border-v-accent bg-v-pale" : "border-v-line bg-v-soft hover:border-v-accent"
          }`}
        >
          <Upload className="size-5 text-v-muted" strokeWidth={1.75} />
          <span className="text-sm font-semibold">{pendingFile ? pendingFile.name : "Drop a PDF here"}</span>
          <span className="text-xs text-v-muted">
            {pendingFile ? formatBytes(pendingFile.size) : "or click to choose a file"}
          </span>
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,application/pdf"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleFile(file);
              e.target.value = "";
            }}
          />
        </div>

        {error ? <p className="text-sm text-v-danger">{error}</p> : null}

        <div className="flex justify-end gap-2 border-t border-v-line pt-4">
          <Button variant="ghost" size="sm" onClick={handleClose}>
            Cancel
          </Button>
          <Button size="sm" disabled={!pendingFile || uploading} onClick={confirmUpload}>
            {uploading ? <Spinner /> : <Upload className="size-3.5" strokeWidth={1.75} />}
            Upload
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
