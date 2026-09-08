"use client";

import { Check } from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface SectionNavItem {
  id: string;
  /** Bold line, e.g. "Agent". Falls back to `label` if omitted. */
  title?: string;
  /** Muted line under the title, e.g. "Name & greeting". */
  subtitle?: string;
  /** @deprecated use `title`/`subtitle` — kept so older call sites still compile. */
  label?: string;
  icon?: LucideIcon;
  disabled?: boolean;
}

interface SectionNavProps {
  items: readonly SectionNavItem[];
  activeId: string;
  onSelect: (id: string) => void;
  /** Small uppercase label centered above the step row, e.g. "Create an agent". */
  eyebrow?: string;
}

/**
 * Sticky step row shared by the agent-creation wizard and the agent edit
 * page: icon, title/subtitle, and a status check per step, dividers between
 * them, the current step's icon inverted to solid dark.
 */
export function SectionNav({ items, activeId, onSelect, eyebrow }: SectionNavProps) {
  const activeIndex = items.findIndex((i) => i.id === activeId);

  return (
    <div className="sticky top-0 z-20 -mx-[34px] -mt-[30px] border-b border-v-line bg-white px-[34px] pb-3 pt-4">
      {eyebrow ? (
        <h1 className="pb-3 text-center font-mono text-[10px] font-semibold uppercase tracking-[.16em] text-v-muted">{eyebrow}</h1>
      ) : null}
      <div className="flex flex-nowrap items-center justify-center gap-x-5 gap-y-2">
        {items.map((item, i) => {
          const active = item.id === activeId;
          const done = activeIndex >= 0 && i < activeIndex;
          const Icon = item.icon;
          return (
            <button
              key={item.id}
              type="button"
              disabled={item.disabled}
              onClick={() => onSelect(item.id)}
              aria-current={active ? "true" : undefined}
              className={`flex shrink-0 cursor-pointer items-center gap-2 rounded-v-md px-3 py-1.5 text-left transition-colors duration-[120ms] disabled:cursor-not-allowed disabled:opacity-45 ${
                active ? "bg-v-soft" : ""
              }`}
            >
              {Icon ? (
                <span
                  className={`flex size-8 shrink-0 items-center justify-center rounded-v-md transition-colors duration-[120ms] ${
                    active ? "bg-v-fg text-white" : "bg-v-soft text-v-muted-2"
                  }`}
                >
                  <Icon className="size-4" strokeWidth={1.8} />
                </span>
              ) : null}
              <span className="flex flex-col gap-0.5">
                <span className="whitespace-nowrap text-[13px] font-semibold text-v-fg">
                  {item.title ?? item.label}
                </span>
                {/* Only the active step shows its subtitle — keeping every other
                    item title-only is what lets all of them fit on one line. */}
                {item.subtitle && active ? (
                  <span className="hidden whitespace-nowrap text-[11px] font-light text-v-muted sm:block">
                    {item.subtitle}
                  </span>
                ) : null}
              </span>
              {!active ? (
                <span
                  className={`flex size-4 shrink-0 items-center justify-center rounded-full ${
                    done ? "bg-v-ok text-white" : "border border-v-line text-v-faint"
                  }`}
                >
                  <Check className="size-2.5" strokeWidth={2.5} />
                </span>
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}
