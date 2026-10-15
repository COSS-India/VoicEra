"use client";

import { ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

interface DialogProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  widthClassName?: string;
  /** Overrides the panel's background/border/text classes — e.g. a dark
   * surface for content (like CallStage) that owns its own theming instead
   * of the default light dialog chrome. */
  panelClassName?: string;
}

export function Dialog({
  open,
  onClose,
  children,
  widthClassName = "max-w-3xl",
  panelClassName = "border border-v-line bg-white",
}: DialogProps) {
  if (!open) return null;
  // Portaled to document.body: an ancestor animated with `animate-v-rise` (or
  // any transform) becomes a containing block for position:fixed descendants
  // per the CSS spec, which would otherwise trap this overlay inside that
  // ancestor's bounds instead of covering the viewport — e.g. a Dialog opened
  // from inside another modal.
  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-[var(--v-overlay)] p-6"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        className={`animate-v-rise flex max-h-[85vh] w-full ${widthClassName} flex-col overflow-y-auto overscroll-contain rounded-v-md shadow-2xl ${panelClassName}`}
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>,
    document.body,
  );
}

export function DialogHeader({
  title,
  subtitle,
  onClose,
  titleEnd,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  /** Optional control rendered beside the title (e.g. a help link). */
  titleEnd?: ReactNode;
}) {
  return (
    <div className="flex shrink-0 flex-wrap items-start justify-between gap-3 border-b border-v-line px-5 py-4">
      <span className="flex min-w-0 flex-1 flex-col gap-0.5 pr-1">
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate text-[17px] font-semibold tracking-tight">{title}</span>
          {titleEnd}
        </span>
        {subtitle ? (
          <span className="text-xs font-light text-v-muted">{subtitle}</span>
        ) : null}
      </span>
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-v-sm border border-v-line text-v-muted transition-colors hover:border-v-line-strong hover:bg-v-track hover:text-v-fg"
      >
        <X className="size-4" strokeWidth={1.75} />
      </button>
    </div>
  );
}
