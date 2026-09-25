"use client";

import type { KeyboardEvent } from "react";
import { Crown, X } from "lucide-react";
import { Tooltip } from "@/components/ui/Tooltip";
import type { LanguagesMap } from "@/lib/catalog-types";
import { languageLabel } from "@/lib/use-wizard-catalogs";

export interface LanguageCardProps {
  lang: string;
  isPrimary: boolean;
  selected: boolean;
  onSelect: () => void;
  onMakePrimary: () => void;
  onRemove: () => void;
  languages: LanguagesMap;
  disabled?: boolean;
}

/** Selectable language badge with crown (set primary) and remove controls. */
export function LanguageCard({
  lang,
  isPrimary,
  selected,
  onSelect,
  onMakePrimary,
  onRemove,
  languages,
  disabled,
}: LanguageCardProps) {
  const label = languageLabel(languages, lang) || lang;

  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect();
    }
  };

  return (
    <div
      className={[
        "group relative flex w-[152px] shrink-0 flex-col rounded-v-md border px-3.5 py-3.5 pr-9 transition-[border-color,box-shadow,background-color] duration-150",
        selected
          ? "border-v-line-strong bg-white shadow-[0_4px_14px_rgba(11,11,12,0.1)]"
          : "border-v-line bg-v-soft/40 shadow-[0_1px_3px_rgba(11,11,12,0.05)] hover:border-v-line-strong hover:bg-white hover:shadow-[0_4px_12px_rgba(11,11,12,0.08)]",
      ].join(" ")}
    >
      <div className="flex items-start gap-2">
        <Tooltip
          text={
            isPrimary
              ? "Sets the default language for the main prompt and multilingual settings"
              : "Set as primary language"
          }
        >
          <button
            type="button"
            disabled={disabled}
            onClick={(e) => {
              e.stopPropagation();
              if (!isPrimary) onMakePrimary();
            }}
            className={[
              "mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-v-sm transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-v-line-strong disabled:cursor-not-allowed disabled:opacity-40",
              isPrimary
                ? "cursor-default bg-v-accent text-white"
                : "cursor-pointer text-v-muted hover:bg-v-soft hover:text-v-fg",
            ].join(" ")}
            aria-label={isPrimary ? "Primary language" : `Set ${label} as primary language`}
            data-testid={`language-crown-${lang}`}
          >
            <Crown className="size-3" strokeWidth={1.75} />
          </button>
        </Tooltip>

        <button
          type="button"
          role="tab"
          aria-selected={selected}
          aria-controls={`language-stack-${lang}`}
          tabIndex={selected ? 0 : -1}
          disabled={disabled}
          onClick={onSelect}
          onKeyDown={onKeyDown}
          className="flex min-w-0 flex-1 cursor-pointer flex-col gap-1.5 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-v-line-strong disabled:cursor-not-allowed disabled:opacity-50"
          id={`language-tab-${lang}`}
          data-testid={`language-badge-${lang}`}
        >
          <span className="truncate text-[15px] font-semibold leading-tight text-v-fg">{label}</span>
          <span
            className={`font-mono text-[10px] uppercase tracking-[.1em] ${
              isPrimary ? "text-v-accent" : "text-v-ok-ink"
            }`}
          >
            {isPrimary ? "Primary" : "Secondary"}
          </span>
        </button>
      </div>

      <button
        type="button"
        disabled={disabled}
        onClick={(e) => {
          e.stopPropagation();
          onRemove();
        }}
        className="absolute right-2 top-2 flex size-7 cursor-pointer items-center justify-center rounded-v-sm text-v-muted opacity-70 transition-opacity hover:bg-v-soft hover:text-v-fg hover:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-v-line-strong disabled:cursor-not-allowed disabled:opacity-40"
        aria-label={`Remove ${label}`}
        data-testid={`language-row-remove-${lang}`}
      >
        <X className="size-3.5" strokeWidth={1.75} />
      </button>
    </div>
  );
}
