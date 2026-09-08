"use client";

import { useState } from "react";

export function Tooltip({
  text,
  children,
}: {
  text: string;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      {children}
      {open ? (
        <span
          role="tooltip"
          className="animate-v-rise absolute left-1/2 top-[calc(100%+8px)] z-50 w-max max-w-64 -translate-x-1/2 rounded-v-sm border border-v-line bg-white px-3 py-2 font-sans text-xs font-normal normal-case leading-relaxed tracking-normal text-v-fg shadow-[0_12px_34px_rgba(11,11,12,.16)]"
        >
          {text}
        </span>
      ) : null}
    </span>
  );
}

export function InfoTip({ text }: { text: string }) {
  return (
    <Tooltip text={text}>
      {/* Isolate from parent typography (e.g. uppercase/tracking mono labels)
          so this always renders like the agent-creation tips. */}
      <span className="inline-flex h-4.5 w-4.5 shrink-0 cursor-help items-center justify-center rounded-full border border-v-line font-mono text-[10px] font-normal normal-case leading-none tracking-normal text-v-muted">
        i
      </span>
    </Tooltip>
  );
}
