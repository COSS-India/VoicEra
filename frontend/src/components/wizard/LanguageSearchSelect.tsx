"use client";

import { LanguageAddSearch } from "@/components/wizard/LanguageAddSearch";
import type { LanguagesMap } from "@/lib/catalog-types";

interface LanguageSearchSelectProps {
  languages: LanguagesMap;
  selected: string[];
  onChange: (ids: string[]) => void;
  disabled?: boolean;
}

/**
 * Legacy language picker (chip list + search). Prefer {@link LanguageConfigList}
 * for the unified accordion UX in the agent wizard.
 */
export function LanguageSearchSelect({
  languages,
  selected,
  onChange,
  disabled,
}: LanguageSearchSelectProps) {
  function removeLanguage(id: string) {
    onChange(selected.filter((x) => x !== id));
  }

  function addLanguage(id: string) {
    onChange([...selected, id]);
  }

  return (
    <div className="flex flex-col gap-3">
      {selected.length === 0 ? (
        <p className="text-sm font-light text-v-muted">Pick at least one language. The first selection is primary.</p>
      ) : selected.length > 5 ? (
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
                  ×
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
                  ×
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <LanguageAddSearch
        languages={languages}
        selected={selected}
        onAdd={addLanguage}
        disabled={disabled}
      />
    </div>
  );
}
