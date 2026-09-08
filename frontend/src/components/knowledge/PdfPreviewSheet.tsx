"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { X } from "lucide-react";

export interface PdfPreviewFile {
  name: string;
  blob?: Blob | string;
}

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])';

/** Reusable slide-in PDF viewer. Fully decoupled from FileCard — it only
 * knows `file` (or null for closed) and `onClose`; nothing calls into it but
 * a parent that owns the "which file is open" state. */
export function PdfPreviewSheet({ file, onClose }: { file: PdfPreviewFile | null; onClose: () => void }) {
  const reduceMotion = useReducedMotion();
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);

  // Blob -> object URL (revoked on cleanup); a string is already a URL.
  useEffect(() => {
    if (!file?.blob) {
      setObjectUrl(null);
      return;
    }
    if (typeof file.blob === "string") {
      setObjectUrl(file.blob);
      return;
    }
    const url = URL.createObjectURL(file.blob);
    setObjectUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  // Body scroll lock + focus capture/restore while open.
  useEffect(() => {
    if (!file) return;
    restoreFocusRef.current = document.activeElement as HTMLElement | null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const raf = requestAnimationFrame(() => closeButtonRef.current?.focus());
    return () => {
      document.body.style.overflow = previousOverflow;
      cancelAnimationFrame(raf);
      restoreFocusRef.current?.focus();
    };
  }, [file]);

  // Escape to close + a basic focus trap while open.
  useEffect(() => {
    if (!file) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key !== "Tab" || !panelRef.current) return;
      const focusable = Array.from(panelRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
      if (focusable.length === 0) return;
      const first = focusable[0]!;
      const last = focusable[focusable.length - 1]!;
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [file, onClose]);

  const panelTransition = reduceMotion
    ? { initial: { opacity: 0 }, animate: { opacity: 1 }, exit: { opacity: 0 } }
    : { initial: { x: "-100%" }, animate: { x: 0 }, exit: { x: "-100%" } };

  return (
    <AnimatePresence>
      {file ? (
        <motion.div
          key="scrim"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="fixed inset-0 z-[200] bg-black/40"
          onClick={onClose}
        >
          <motion.div
            key="panel"
            ref={panelRef}
            role="dialog"
            aria-modal="true"
            aria-label={`Preview of ${file.name}`}
            initial={panelTransition.initial}
            animate={panelTransition.animate}
            exit={panelTransition.exit}
            transition={reduceMotion ? { duration: 0.15 } : { type: "spring", stiffness: 380, damping: 38 }}
            className="fixed left-0 top-0 flex h-full w-full flex-col overflow-hidden border-r border-[#E3E0D6] bg-white shadow-2xl sm:w-1/2"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex shrink-0 items-center justify-between gap-3 border-b border-[#E3E0D6] px-4.5 py-4">
              <span className="min-w-0 truncate text-[15px] font-medium text-[#20201C]" title={file.name}>
                {file.name}
              </span>
              <button
                ref={closeButtonRef}
                type="button"
                aria-label="Close preview"
                onClick={onClose}
                className="flex size-11 shrink-0 cursor-pointer items-center justify-center rounded-md text-[#7A7669] transition-colors hover:bg-[#F3F1EA] hover:text-[#20201C]"
              >
                <X className="size-4.5" strokeWidth={1.9} />
              </button>
            </div>

            <div className="flex-1 overflow-y-auto bg-[#F7F6F2]">
              {objectUrl ? (
                <iframe src={objectUrl} title={file.name} className="h-full w-full border-0" />
              ) : (
                <div className="flex h-full flex-col items-center justify-center gap-1.5 p-8 text-center">
                  <span className="text-sm font-medium text-[#20201C]">Preview not available</span>
                  <span className="max-w-[32ch] text-xs font-light text-[#7A7669]">
                    This document can&apos;t be previewed yet.
                  </span>
                </div>
              )}
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
