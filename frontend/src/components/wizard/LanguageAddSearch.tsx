"use client";

import { useMemo, useRef, useState } from "react";
import { ChevronDown, Search } from "lucide-react";
import type { LanguagesMap } from "@/lib/catalog-types";

interface LanguageAddSearchProps {
  languages: LanguagesMap;
  selected: string[];
  onAdd: (id: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

/** Search-and-pick control for adding a language. */
export function LanguageAddSearch({
  languages,
  selected,
  onAdd,
  disabled,
  placeholder = "Search languages to add…",
}: LanguageAddSearchProps) {
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

  function pickLanguage(id: string) {
    onAdd(id);
    setQuery("");
    setOpen(false);
  }

  return (
    <div ref={containerRef} className="relative">
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
        placeholder={placeholder}
        aria-label={placeholder}
        className="w-full rounded-v-sm border border-v-line-strong bg-white py-2.5 pl-10 pr-10 text-[14px] focus:border-v-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-v-accent/30 disabled:bg-v-soft/60"
      />
      <ChevronDown
        className={`pointer-events-none absolute right-3.5 top-1/2 size-4 -translate-y-1/2 text-v-muted transition-transform duration-200 ${
          open ? "rotate-180" : ""
        }`}
        strokeWidth={1.75}
        aria-hidden
      />

      {open && options.length > 0 ? (
        <ul
          role="listbox"
          className="absolute inset-x-0 top-full z-20 mt-1 max-h-56 overflow-y-auto rounded-v-sm border border-v-line bg-white py-1 shadow-[0_8px_24px_rgba(11,11,12,0.08)]"
        >
          {options.map(([id, label]) => (
            <li key={id} role="option">
              <button
                type="button"
                className="flex w-full cursor-pointer flex-col items-start gap-0.5 px-3.5 py-2.5 text-left hover:bg-v-soft/80 focus-visible:bg-v-soft/80 focus-visible:outline-none"
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => pickLanguage(id)}
              >
                <span className="text-[14px] font-medium">{label}</span>
                <span className="font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">{id}</span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      {open && query.trim() && options.length === 0 ? (
        <div className="absolute inset-x-0 top-full z-20 mt-1 rounded-v-sm border border-v-line bg-white px-3.5 py-3 text-sm text-v-muted shadow-[0_8px_24px_rgba(11,11,12,0.08)]">
          No languages match &ldquo;{query.trim()}&rdquo;.
        </div>
      ) : null}
    </div>
  );
}
