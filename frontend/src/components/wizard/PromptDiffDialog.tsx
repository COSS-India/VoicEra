"use client";

import { useMemo } from "react";
import { Button } from "@/components/ui/Button";
import { diffWords } from "@/lib/word-diff";

interface PromptDiffViewProps {
  original: string;
  refined: string;
  onAccept: () => void;
  onReject: () => void;
}

/** Inline diff shown in place of the prompt editor while a refinement is pending review. */
export function PromptDiffView({ original, refined, onAccept, onReject }: PromptDiffViewProps) {
  const tokens = useMemo(() => diffWords(original, refined), [original, refined]);

  return (
    <div className="flex min-h-[240px] flex-col overflow-hidden rounded-v-md border border-v-accent/40 bg-white">
      <div className="max-h-[400px] overflow-y-auto whitespace-pre-wrap p-3 text-[13px] leading-relaxed text-v-fg">
        {tokens.map((token, idx) => {
          if (token.type === "added") {
            return (
              <span key={idx} className="rounded-[2px] bg-v-accent/15 text-v-accent-deep">
                {token.text}
              </span>
            );
          }
          if (token.type === "removed") {
            return (
              <span key={idx} className="rounded-[2px] bg-v-danger-pale text-v-danger line-through">
                {token.text}
              </span>
            );
          }
          return <span key={idx}>{token.text}</span>;
        })}
      </div>
      <div className="flex shrink-0 items-center justify-end gap-2 border-t border-v-line bg-v-soft/40 px-3 py-2.5">
        <Button type="button" size="sm" variant="outline" onClick={onReject}>
          Keep original
        </Button>
        <Button type="button" size="sm" variant="primary" onClick={onAccept}>
          Use refined
        </Button>
      </div>
    </div>
  );
}
