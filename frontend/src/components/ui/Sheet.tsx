"use client";

import { ReactNode } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";

interface SheetProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  widthClassName?: string;
}

/** Right-side slide-in panel — the Dialog's counterpart for flows that read like a
 * form drawer (test call, etc.) rather than a centered confirmation. */
export function Sheet({ open, onClose, children, widthClassName = "max-w-md" }: SheetProps) {
  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          key="overlay"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          className="fixed inset-0 z-[100] bg-[var(--v-overlay)]"
          onClick={onClose}
        >
          <motion.div
            key="panel"
            initial={{ x: "100%" }}
            animate={{ x: 0 }}
            exit={{ x: "100%" }}
            transition={{ type: "spring", stiffness: 380, damping: 38 }}
            className={`fixed right-0 top-0 flex h-full w-full ${widthClassName} flex-col overflow-hidden border-l border-v-line bg-white shadow-2xl`}
            onClick={(e) => e.stopPropagation()}
          >
            {children}
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}

export function SheetHeader({
  title,
  subtitle,
  icon,
  onClose,
}: {
  title: string;
  subtitle?: string;
  icon?: ReactNode;
  onClose: () => void;
}) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-v-line px-5 py-5">
      <div className="flex items-start gap-3">
        {icon ? (
          <span className="flex size-9 shrink-0 items-center justify-center rounded-v-sm bg-v-soft text-v-fg">
            {icon}
          </span>
        ) : null}
        <span className="flex flex-col gap-1">
          <span className="text-[19px] font-semibold tracking-tight">{title}</span>
          {subtitle ? (
            <span className="text-[13px] font-light leading-snug text-v-muted">{subtitle}</span>
          ) : null}
        </span>
      </div>
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-v-sm text-v-muted transition-colors hover:bg-v-soft hover:text-v-fg"
      >
        <X className="size-4" strokeWidth={1.75} />
      </button>
    </div>
  );
}
