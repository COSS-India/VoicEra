"use client";

import { useMemo, useState } from "react";
import { Input, Select } from "@/components/ui/Field";
import { Button } from "@/components/ui/Button";
import { AgentTemplate, TEMPLATES, TPL_CATS } from "@/lib/wizard-data";

interface StartStepProps {
  onStartScratch: () => void;
  onUseTemplate: (t: AgentTemplate) => void;
}

export function StartStep({ onStartScratch, onUseTemplate }: StartStepProps) {
  const [browsing, setBrowsing] = useState(false);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("All");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return TEMPLATES.filter((t) => {
      const matchesCat = category === "All" || t.category === category;
      const matchesQuery =
        !q || t.name.toLowerCase().includes(q) || t.note.toLowerCase().includes(q);
      return matchesCat && matchesQuery;
    });
  }, [query, category]);

  if (!browsing) {
    return (
      <div className="flex flex-col gap-7 animate-v-rise">
        <div className="flex flex-col gap-2">
          <h1 className="text-[28px] font-semibold tracking-tight">
            How would you like to begin?
          </h1>
          <p className="max-w-[56ch] text-sm font-light leading-relaxed text-v-muted-2">
            Both paths end in the same place — an agent that answers the phone in your
            caller&rsquo;s language.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2">
          <button
            type="button"
            data-tour="start-from-scratch"
            onClick={onStartScratch}
            className="flex cursor-pointer flex-col gap-3.5 rounded-v-md border border-v-line bg-white p-5 text-left transition-colors hover:border-v-accent"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-full bg-v-fg text-white">
              +
            </span>
            <span className="flex flex-col gap-1.5">
              <span className="text-lg font-semibold tracking-tight">Start from scratch</span>
              <span className="text-[13.5px] font-light leading-relaxed text-v-muted">
                Four short screens — one decision at a time, then a test call.
              </span>
            </span>
            <span className="font-mono text-[10.5px] uppercase tracking-[.1em] text-v-muted">
              Guided · about 3 minutes
            </span>
          </button>

          <button
            type="button"
            onClick={() => setBrowsing(true)}
            className="flex cursor-pointer flex-col gap-3.5 rounded-v-md border border-v-line bg-white p-5 text-left transition-colors hover:border-v-accent"
          >
            <span className="flex h-10 w-10 items-center justify-center rounded-full bg-v-soft text-v-fg">
              ▦
            </span>
            <span className="flex flex-col gap-1.5">
              <span className="text-lg font-semibold tracking-tight">
                Start from a template
              </span>
              <span className="text-[13.5px] font-light leading-relaxed text-v-muted">
                A working agent, already written. Change anything you like.
              </span>
            </span>
            <span className="font-mono text-[10.5px] uppercase tracking-[.1em] text-v-muted">
              Fastest · about 30 seconds
            </span>
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5 animate-v-rise">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-2">
          <Button variant="ghost" size="sm" className="w-max" onClick={() => setBrowsing(false)}>
            ← Back
          </Button>
          <h1 className="text-[26px] font-semibold tracking-tight">Pick a template</h1>
        </div>
        <span className="font-mono text-[10px] uppercase tracking-[.14em] text-v-muted">
          {filtered.length} templates
        </span>
      </div>

      <div className="flex flex-wrap gap-2.5">
        <Input
          className="min-w-64 flex-1"
          placeholder="Search templates"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <Select className="w-max" value={category} onChange={(e) => setCategory(e.target.value)}>
          {TPL_CATS.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </Select>
      </div>

      <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
        {filtered.map((t) => (
          <div
            key={t.id}
            className="flex flex-col gap-3 rounded-v-md border border-v-line bg-white p-4.5"
          >
            <span className="flex items-start justify-between gap-2">
              <span className="text-[15px] font-semibold tracking-tight">{t.name}</span>
              <span className="whitespace-nowrap font-mono text-[9px] uppercase tracking-[.12em] text-v-muted">
                by {t.by}
              </span>
            </span>
            <span className="text-xs font-light leading-relaxed text-v-muted">{t.note}</span>
            <span className="border-l-2 border-v-accent pl-2.5 text-[12.5px] leading-relaxed text-v-fg">
              {t.line}
            </span>
            <span className="flex items-center justify-between gap-2 border-t border-v-line pt-3">
              <span className="font-mono text-[9.5px] uppercase tracking-[.1em] text-v-muted">
                {t.category} · {t.lang}
              </span>
              <Button size="sm" onClick={() => onUseTemplate(t)}>
                Use this
              </Button>
            </span>
          </div>
        ))}

        {filtered.length === 0 ? (
          <div className="col-span-full flex flex-col items-center gap-1.5 rounded-v-md border border-v-line bg-white p-9 text-center">
            <span className="text-sm font-semibold">Nothing matches that</span>
            <span className="text-xs font-light text-v-muted">
              Try another word, or start from scratch.
            </span>
          </div>
        ) : null}
      </div>
    </div>
  );
}
