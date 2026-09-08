"use client";

import { useMemo, useRef, useState } from "react";
import { ChevronDown, Search, X } from "lucide-react";
import type { LanguagesMap } from "@/lib/catalog-types";

interface LanguageSearchSelectProps {
  languages: LanguagesMap;
  selected: string[];
  onChange: (ids: string[]) => void;
  disabled?: boolean;
}

export function LanguageSearchSelect({
  languages,
  selected,
  onChange,
  disabled,
}: LanguageSearchSelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

  const options = useMemo(() => {
    const q = query.trim().toLowerCase();
    return Object.entries(languages)
      .filter(([id, label]) => {
        if (selected.includes(id)) return false;
        if (!q) return true;
        return label.toLowerCase().includes(q) || id.toLowerCase().includes(q);
      })
      .sort(([, a], [, b]) => a.localeCompare(b));
  }, [languages, selected, query]);

  function addLanguage(id: string) {
    onChange([...selected, id]);
    setQuery("");
    setOpen(false);
  }

  function removeLanguage(id: string) {
    onChange(selected.filter((x) => x !== id));
  }

  return (
    <div ref={containerRef} className="flex flex-col gap-3">
      {selected.length === 0 ? (
        <p className="text-sm font-light text-v-muted">Pick at least one language. The first selection is primary.</p>
      ) : selected.length > 5 ? (
        // Past 5, full-width bars would push the page tall/awkward — compact
        // badges keep an arbitrary number of languages on a couple of wrapped
        // lines instead of overflowing.
        <div className="flex flex-wrap gap-1.5">
          {selected.map((id, index) => {
            const isPrimary = index === 0;
            return (
              <span
                key={id}
                title={isPrimary ? "Primary language" : `Secondary · ${index + 1}`}
                className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${
                  isPrimary ? "border-v-accent bg-v-pale text-v-accent-deep" : "border-v-ok bg-v-ok-tint text-v-ok-ink"
                }`}
              >
                {languages[id] ?? id}
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => removeLanguage(id)}
                  className="flex size-3.5 shrink-0 cursor-pointer items-center justify-center rounded-full hover:bg-white/70 disabled:cursor-not-allowed disabled:opacity-40"
                  aria-label={`Remove ${languages[id] ?? id}`}
                >
                  <X className="size-2.5" strokeWidth={2.25} />
                </button>
              </span>
            );
          })}
        </div>
      ) : (
        <ul className="flex flex-col gap-2">
          {selected.map((id, index) => {
            const isPrimary = index === 0;
            return (
              <li
                key={id}
                className={`flex items-center justify-between gap-3 rounded-v-sm border-2 bg-v-soft/40 px-3.5 py-2.5 ${
                  isPrimary ? "border-v-accent" : "border-v-ok"
                }`}
              >
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="text-[14px] font-medium text-v-fg">{languages[id] ?? id}</span>
                  <span
                    className={`font-mono text-[10px] uppercase tracking-[.1em] ${
                      isPrimary ? "text-v-accent" : "text-v-ok-ink"
                    }`}
                  >
                    {isPrimary ? "Primary language" : `Secondary · ${index + 1}`}
                  </span>
                </span>
                <button
                  type="button"
                  disabled={disabled}
                  onClick={() => removeLanguage(id)}
                  className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-v-sm text-v-muted transition-colors hover:bg-white hover:text-v-fg disabled:cursor-not-allowed disabled:opacity-40"
                  aria-label={`Remove ${languages[id] ?? id}`}
                >
                  <X className="size-4" strokeWidth={1.75} />
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <div className="relative">
        <Search
          className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-v-muted"
          strokeWidth={1.75}
        />
        <input
          type="search"
          disabled={disabled}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => {
            window.setTimeout(() => setOpen(false), 150);
          }}
          placeholder="Search languages to add…"
          className="w-full rounded-v-sm border border-v-line-strong bg-white py-2.5 pl-10 pr-10 text-[14px] focus:border-v-accent focus:outline-none disabled:bg-v-soft/60"
        />
        <ChevronDown
          className={`pointer-events-none absolute right-3.5 top-1/2 size-4 -translate-y-1/2 text-v-muted transition-transform ${
            open ? "rotate-180" : ""
          }`}
          strokeWidth={1.75}
        />

        {open && options.length > 0 ? (
          <ul className="absolute z-20 mt-1 max-h-56 w-full overflow-y-auto rounded-v-sm border border-v-line bg-white py-1 shadow-[0_8px_24px_rgba(11,11,12,0.08)]">
            {options.map(([id, label]) => (
              <li key={id}>
                <button
                  type="button"
                  className="flex w-full cursor-pointer flex-col items-start gap-0.5 px-3.5 py-2.5 text-left hover:bg-v-soft/80"
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => addLanguage(id)}
                >
                  <span className="text-[14px] font-medium">{label}</span>
                  <span className="font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">{id}</span>
                </button>
              </li>
            ))}
          </ul>
        ) : null}

        {open && query.trim() && options.length === 0 ? (
          <div className="absolute z-20 mt-1 w-full rounded-v-sm border border-v-line bg-white px-3.5 py-3 text-sm text-v-muted shadow-[0_8px_24px_rgba(11,11,12,0.08)]">
            No languages match &ldquo;{query.trim()}&rdquo;.
          </div>
        ) : null}
      </div>
    </div>
  );
}
