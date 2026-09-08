"use client";

import { useMemo, useState } from "react";
import { Dialog, DialogHeader } from "@/components/ui/Dialog";
import { Input } from "@/components/ui/Field";
import { Button } from "@/components/ui/Button";
import { CATEGORIES, PROMPT_MODULES, PromptModule } from "@/lib/prompt-modules";

interface PromptLibraryDialogProps {
  open: boolean;
  onClose: () => void;
  currentPrompt: string;
  onInsert: (module: PromptModule) => void;
}

export function PromptLibraryDialog({
  open,
  onClose,
  currentPrompt,
  onInsert,
}: PromptLibraryDialogProps) {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("All");
  const [selectedId, setSelectedId] = useState(PROMPT_MODULES[0].id);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return PROMPT_MODULES.filter((m) => {
      const matchesCategory = category === "All" || m.category === category;
      const matchesQuery =
        !q || m.name.toLowerCase().includes(q) || m.short.toLowerCase().includes(q);
      return matchesCategory && matchesQuery;
    });
  }, [query, category]);

  const selected = filtered.find((m) => m.id === selectedId) ?? filtered[0] ?? null;
  const alreadyAdded = (m: PromptModule) => currentPrompt.includes(m.text);

  return (
    <Dialog open={open} onClose={onClose} widthClassName="max-w-4xl">
      <DialogHeader
        title="Prompt modules"
        subtitle="Behaviours other teams already tuned. Pick one to read it, then insert."
        onClose={onClose}
      />
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[1.35fr_1fr]">
        <div className="flex min-h-0 flex-col gap-2.5 overflow-y-auto border-b border-v-line p-4 lg:border-b-0 lg:border-r">
          <Input
            placeholder="Search behaviours"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="flex flex-wrap gap-1.5">
            {CATEGORIES.map((c) => (
              <button
                key={c}
                onClick={() => setCategory(c)}
                className={`cursor-pointer rounded-full border px-2.5 py-1 text-xs font-medium transition-colors ${
                  category === c
                    ? "border-v-fg bg-v-fg text-white"
                    : "border-v-line bg-white text-v-muted-2 hover:border-v-accent"
                }`}
              >
                {c}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {filtered.map((m) => {
              const added = alreadyAdded(m);
              return (
                <button
                  key={m.id}
                  onClick={() => setSelectedId(m.id)}
                  className={`flex cursor-pointer flex-col gap-1.5 rounded-v-sm border p-3 text-left transition-colors ${
                    selected?.id === m.id
                      ? "border-v-accent bg-v-pale/40"
                      : "border-v-line bg-white hover:border-v-accent"
                  } ${added ? "opacity-60" : ""}`}
                >
                  <span className="inline-flex w-max items-center rounded-full bg-v-soft px-2 py-0.5 font-mono text-[9px] uppercase tracking-[.1em] text-v-muted">
                    {added ? "Added" : m.tag}
                  </span>
                  <span className="text-[12px] font-semibold leading-snug">{m.name}</span>
                  <span className="line-clamp-2 text-[10.5px] font-light leading-relaxed text-v-muted">
                    {m.short}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex min-h-0 flex-col gap-4 overflow-y-auto p-5">
          {selected ? (
            <>
              <div className="flex flex-col gap-1">
                <span className="font-mono text-[9.5px] uppercase tracking-[.14em] text-v-muted">
                  {selected.category}
                </span>
                <span className="text-xl font-semibold tracking-tight">{selected.name}</span>
              </div>
              <div className="flex flex-col gap-1.5">
                <span className="font-mono text-[9.5px] uppercase tracking-[.14em] text-v-muted">
                  Preview · {selected.text.length} chars
                </span>
                <span className="rounded-v-sm border-l-2 border-v-accent bg-v-soft px-3.5 py-3 text-sm leading-relaxed text-v-fg">
                  {selected.text}
                </span>
              </div>
              <div className="flex flex-col gap-1.5">
                <span className="font-mono text-[9.5px] uppercase tracking-[.14em] text-v-muted">
                  What it is for
                </span>
                <span className="text-[13px] font-light leading-relaxed text-v-muted-2">
                  {selected.why}
                </span>
              </div>
              <div className="mt-auto flex flex-wrap items-center gap-2.5 border-t border-v-line pt-3.5">
                <Button
                  size="sm"
                  disabled={alreadyAdded(selected)}
                  onClick={() => {
                    onInsert(selected);
                    onClose();
                  }}
                >
                  {alreadyAdded(selected) ? "Already in your instructions" : "Insert into instructions"}
                </Button>
              </div>
            </>
          ) : (
            <span className="m-auto text-sm text-v-muted">Nothing selected</span>
          )}
        </div>
      </div>
    </Dialog>
  );
}
