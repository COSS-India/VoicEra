"use client";

import { useMemo, useState } from "react";
import { Search, Upload } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Switch } from "@/components/ui/Switch";
import { Spinner } from "@/components/ui/Spinner";
import { InfoTip } from "@/components/ui/Tooltip";
import { PromptEditor } from "@/components/wizard/PromptEditor";
import { VariablesPanel } from "@/components/wizard/VariablesPanel";
import { UploadDocumentDialog } from "@/components/knowledge/UploadDocumentDialog";
import { useKnowledgeBase } from "@/hooks/useKnowledgeBase";
import { PROMPT_MODULES } from "@/lib/prompt-modules";
import { TIPS, type AgentForm } from "@/lib/wizard-data";

interface PromptKnowledgeStepProps {
  form: AgentForm;
  onChange: <K extends keyof AgentForm>(key: K, value: AgentForm[K]) => void;
  onOpenLibrary: () => void;
  onNotify: (title: string, note: string) => void;
}

export function PromptKnowledgeStep({ form, onChange, onOpenLibrary, onNotify }: PromptKnowledgeStepProps) {
  // Same hook the Knowledge Base page itself uses — one source of truth for
  // documents, upload, and status, so a PDF added here shows up there too
  // (and vice versa) without a separate fetch/reload path.
  const kb = useKnowledgeBase(onNotify);
  const [docQuery, setDocQuery] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);

  const filteredDocs = useMemo(() => {
    const q = docQuery.trim().toLowerCase();
    if (!q) return kb.documents;
    return kb.documents.filter((d) => d.original_filename.toLowerCase().includes(q));
  }, [kb.documents, docQuery]);

  return (
    <div className="flex flex-col gap-6 animate-v-rise">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="flex items-center gap-1.5 text-[13px] font-semibold">
            System prompt
            <InfoTip text={TIPS.prompt} />
          </span>
          <Button type="button" size="sm" variant="outline" onClick={onOpenLibrary}>
            Browse prompt modules
          </Button>
        </div>
        <div data-tour="prompt-textarea">
          <PromptEditor
            value={form.prompt}
            onChange={(v) => onChange("prompt", v)}
            variables={Object.keys(form.customVariables)}
            promptModules={PROMPT_MODULES}
            placeholder="You are…"
            rows={11}
          />
        </div>
        <p className="text-xs font-light text-v-muted ">
          Type <code className="rounded-v-sm bg-v-soft px-1 py-0.5 font-mono text-[11px]">{"{"}</code> for a
          variable, or <code className="rounded-v-sm bg-v-soft px-1 py-0.5 font-mono text-[11px]">/</code> to search
          prompt modules.
        </p>
      </div>

      <VariablesPanel form={form} onChange={onChange} />

      <div className="flex flex-col gap-3 rounded-v-md border border-v-line bg-white p-5 mb-10">
        <div className="flex items-center justify-between gap-3 ">
          <span className="flex items-center gap-3">
            <Switch
              checked={form.kbEnabled}
              label="Use knowledge base"
              onChange={(checked) => onChange("kbEnabled", checked)}
            />
            <span className="flex items-center gap-1.5 text-[13px] font-medium text-v-fg">
              Use knowledge base
              <InfoTip text={TIPS.kb} />
            </span>
          </span>
          {form.kbEnabled ? (
            <Button type="button" size="sm" variant="outline" onClick={() => setUploadOpen(true)}>
              <Upload className="size-3.5" strokeWidth={1.75} />
              Upload knowledge base
            </Button>
          ) : null}
        </div>

        {form.kbEnabled ? (
          <div className="flex flex-col gap-2.5 rounded-v-md border border-v-line bg-v-soft/40 p-3">
            <span className="text-[13px] font-semibold">Documents</span>

            {kb.documents.length > 0 ? (
              <div className="relative">
                <Search
                  className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-v-muted"
                  strokeWidth={1.75}
                />
                <input
                  type="search"
                  placeholder="Search documents…"
                  value={docQuery}
                  onChange={(e) => setDocQuery(e.target.value)}
                  className="w-full rounded-v-sm border border-v-line-strong bg-white py-2 pl-8 pr-3 text-[13px] text-v-fg transition-colors focus:border-v-accent focus:outline-none"
                />
              </div>
            ) : null}

            {kb.loading ? (
              <p className="flex items-center gap-2 text-[13px] font-light text-v-muted">
                <Spinner light={false} /> Getting knowledge base documents…
              </p>
            ) : kb.loadError ? (
              <p className="text-[13px] font-light text-v-danger">{kb.loadError}</p>
            ) : filteredDocs.length ? (
              <div className="flex max-h-64 flex-col gap-1.5 overflow-y-auto">
                {filteredDocs.map((d) => {
                  const checked = form.kbDocs.includes(d.document_id);
                  const disabled = d.status !== "ready";
                  return (
                    <label
                      key={d.document_id}
                      className={`flex items-center gap-2.5 rounded-v-sm border border-v-line bg-white px-3 py-2 text-[13px] ${
                        disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer hover:border-v-accent"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={disabled}
                        onChange={() => {
                          const next = checked
                            ? form.kbDocs.filter((x) => x !== d.document_id)
                            : [...form.kbDocs, d.document_id];
                          onChange("kbDocs", next);
                        }}
                      />
                      <span className="min-w-0 flex-1 truncate">{d.original_filename}</span>
                      {disabled ? (
                        <span className="shrink-0 text-v-muted">
                          {d.status === "processing" ? "processing…" : "failed"}
                        </span>
                      ) : null}
                    </label>
                  );
                })}
              </div>
            ) : docQuery ? (
              <p className="text-[13px] font-light text-v-muted">No documents match &ldquo;{docQuery}&rdquo;.</p>
            ) : (
              <p className="text-[13px] font-light text-v-muted">
                No documents uploaded yet — use &ldquo;Upload knowledge base&rdquo; above to add a PDF.
              </p>
            )}
          </div>
        ) : null}
      </div>

      <UploadDocumentDialog
        open={uploadOpen}
        uploading={kb.uploading}
        onUpload={kb.upload}
        onClose={() => setUploadOpen(false)}
      />
    </div>
  );
}
