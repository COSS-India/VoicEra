"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, Search } from "lucide-react";
import { ProviderTypeBadge } from "@/components/ui/ProviderTypeBadge";
import { dropdownMenuCoords, type DropdownMenuCoords } from "@/lib/dropdown-placement";

export interface SearchSelectOption {
  value: string;
  label: string;
  /** Shown as a chip beside the label (e.g. cloud / local provider type). */
  providerType?: string | null;
  /** Rendered but not selectable — e.g. a provider not connected under Integrations. */
  disabled?: boolean;
}

const MENU_MARGIN = 4;
/** Search field + border; subtracted so the options list gets the leftover height. */
const SEARCH_HEADER_H = 41;
/** Matches the old max-h-56 on the options list. */
const LIST_DESIRED = 224;
const MENU_DESIRED = SEARCH_HEADER_H + LIST_DESIRED;

function menuCoordsFor(rect: DOMRect): DropdownMenuCoords {
  return dropdownMenuCoords(rect, MENU_DESIRED, MENU_MARGIN);
}

function OptionLabel({ option, muted }: { option: SearchSelectOption; muted?: boolean }) {
  return (
    <span className={`flex min-w-0 items-center gap-2 ${muted ? "text-v-muted" : ""}`}>
      <span className="min-w-0 truncate">{option.label}</span>
      <ProviderTypeBadge providerType={option.providerType} />
    </span>
  );
}

/**
 * Single-value dropdown with a search box, for pickers with enough options
 * that scanning a plain <select> is slow (e.g. every STT/TTS/LLM provider).
 * Options can be individually disabled — shown, but not selectable — so a
 * picker can list every possibility while only letting the user land on the
 * ones this org actually has configured. The menu is portaled to <body> (like
 * Select.tsx) so it's never clipped by a scrolling ancestor, and opens above
 * or below the trigger based on available viewport space.
 */
export function SearchSelect({
  options,
  value,
  onChange,
  placeholder = "Select…",
  disabled,
}: {
  options: SearchSelectOption[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [coords, setCoords] = useState<DropdownMenuCoords | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDocMouseDown(e: MouseEvent) {
      if (menuRef.current?.contains(e.target as Node) || btnRef.current?.contains(e.target as Node)) return;
      setOpen(false);
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    function reposition() {
      if (!btnRef.current) return;
      setCoords(menuCoordsFor(btnRef.current.getBoundingClientRect()));
    }
    reposition();
    document.addEventListener("mousedown", onDocMouseDown);
    document.addEventListener("keydown", onKeyDown);
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
    return () => {
      document.removeEventListener("mousedown", onDocMouseDown);
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("scroll", reposition, true);
      window.removeEventListener("resize", reposition);
    };
  }, [open]);

  const selected = options.find((o) => o.value === value);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return options;
    return options.filter((o) => {
      const type = o.providerType?.toLowerCase() ?? "";
      return o.label.toLowerCase().includes(q) || type.includes(q);
    });
  }, [options, query]);

  function pick(o: SearchSelectOption) {
    if (o.disabled) return;
    onChange(o.value);
    setQuery("");
    setOpen(false);
  }

  function toggle() {
    if (disabled) return;
    if (!open && btnRef.current) {
      setCoords(menuCoordsFor(btnRef.current.getBoundingClientRect()));
    }
    setOpen((v) => !v);
  }

  const listMaxHeight = coords ? Math.max(80, coords.maxHeight - SEARCH_HEADER_H) : LIST_DESIRED;

  return (
    <div className="relative">
      <button
        ref={btnRef}
        type="button"
        disabled={disabled}
        onClick={toggle}
        className="flex w-full box-border cursor-pointer items-center justify-between gap-2 rounded-v-lg border border-v-line-strong bg-white px-3.5 py-[11px] text-left text-[13.5px] text-v-fg transition-colors hover:border-v-accent focus:border-v-accent focus:outline-none disabled:cursor-not-allowed disabled:opacity-50"
      >
        {selected ? (
          <OptionLabel option={selected} />
        ) : (
          <span className="min-w-0 truncate text-v-muted">{placeholder}</span>
        )}
        <ChevronDown
          className={`size-[13px] shrink-0 text-v-faint transition-transform ${open ? "rotate-180" : ""}`}
          strokeWidth={2}
        />
      </button>

      {open && coords
        ? createPortal(
            <div
              ref={menuRef}
              style={{
                position: "fixed",
                left: coords.left,
                width: coords.width,
                maxHeight: coords.maxHeight,
                ...(coords.top !== undefined ? { top: coords.top } : { bottom: coords.bottom }),
              }}
              className="z-[1000] flex flex-col overflow-hidden rounded-v-sm border border-v-line bg-white shadow-[0_8px_24px_rgba(11,11,12,0.12)]"
            >
              <div className="relative shrink-0 border-b border-v-line">
                <Search
                  className="pointer-events-none absolute left-3 top-1/2 size-3.5 -translate-y-1/2 text-v-muted"
                  strokeWidth={1.75}
                />
                <input
                  autoFocus
                  type="search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search…"
                  className="w-full py-2 pl-8 pr-3 text-[13px] focus:outline-none"
                />
              </div>
              <div className="min-h-0 overflow-y-auto py-1" style={{ maxHeight: listMaxHeight }}>
                {filtered.length === 0 ? (
                  <div className="px-3.5 py-2.5 text-sm text-v-muted">No matches.</div>
                ) : (
                  filtered.map((o) => (
                    <button
                      key={o.value}
                      type="button"
                      role="option"
                      aria-selected={o.value === value}
                      disabled={o.disabled}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => pick(o)}
                      className={`flex w-full items-center justify-between gap-2 px-3.5 py-2.5 text-left text-[13.5px] transition-colors hover:bg-v-soft disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent ${
                        o.value === value ? "bg-v-soft font-medium text-v-fg" : "text-v-fg"
                      }`}
                    >
                      <OptionLabel option={o} />
                    </button>
                  ))
                )}
              </div>
            </div>,
            document.body,
          )
        : null}
    </div>
  );
}
