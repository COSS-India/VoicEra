"use client";

import { Pencil } from "lucide-react";

export type LanguageStackSummary = {
  langId: string;
  label: string;
  isPrimary: boolean;
  stt: string;
  tts: string;
  llm: string;
};

function ServiceRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="w-8 shrink-0 font-mono text-[9.5px] uppercase tracking-[.1em] text-v-muted">
        {label}
      </dt>
      <dd className="min-w-0 break-words text-[12.5px] font-medium leading-snug text-v-fg">
        {value || "—"}
      </dd>
    </div>
  );
}

/** Per-language STT / TTS / LLM cards for test modal and wizard review. */
export function LanguageStacksPanel({
  stacks,
  onEdit,
}: {
  stacks: LanguageStackSummary[];
  onEdit?: () => void;
}) {
  if (!stacks.length) {
    return <p className="text-[12.5px] text-v-muted">No language stacks configured.</p>;
  }

  return (
    <div className="flex flex-col gap-2.5">
      {stacks.map((stack) => (
        <div
          key={stack.langId}
          className="rounded-v-sm border border-v-line bg-white px-3 py-2.5"
        >
          <div className="mb-2 flex items-center justify-between gap-2">
            <span className="flex min-w-0 items-center gap-1.5">
              <span className="truncate text-[13px] font-semibold text-v-fg">{stack.label}</span>
              {stack.isPrimary ? (
                <span className="shrink-0 rounded-v-sm bg-v-soft px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-[.08em] text-v-muted">
                  Primary
                </span>
              ) : null}
            </span>
            {onEdit ? (
              <button
                type="button"
                aria-label={`Edit ${stack.label} stack`}
                onClick={onEdit}
                className="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-v-sm border border-v-line text-v-muted transition-colors hover:bg-v-soft hover:text-v-fg"
              >
                <Pencil className="size-3.5" strokeWidth={1.8} />
              </button>
            ) : null}
          </div>
          <dl className="flex flex-col gap-1.5">
            <ServiceRow label="STT" value={stack.stt} />
            <ServiceRow label="TTS" value={stack.tts} />
            <ServiceRow label="LLM" value={stack.llm} />
          </dl>
        </div>
      ))}
    </div>
  );
}

/** Build a single “Provider · model · voice” line. */
export function formatServiceLine(
  providerName: string,
  model?: string,
  voice?: string,
): string {
  const parts = [providerName || "—"];
  if (model) parts.push(model);
  if (voice) parts.push(voice);
  return parts.join(" · ");
}
