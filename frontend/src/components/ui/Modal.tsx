"use client";

import { useState } from "react";
import { Button } from "./Button";

export function ModalDemo() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        Open modal
      </Button>
      {open ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--v-overlay)] p-6"
          onClick={() => setOpen(false)}
        >
          <div
            className="animate-v-rise flex w-full max-w-md flex-col overflow-hidden rounded-v-md border border-v-line bg-white shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between gap-3 border-b border-v-line px-5 py-4">
              <span className="flex flex-col gap-0.5">
                <span className="text-[15px] font-semibold">Prompt modules</span>
                <span className="text-xs font-light text-v-muted">
                  Behaviours other teams already tuned.
                </span>
              </span>
              <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
                Close
              </Button>
            </div>
            <div className="p-5 text-sm leading-relaxed text-v-muted-2">
              This is the modal shell used across VoicEra — see the{" "}
              <span className="font-medium text-v-fg">Library</span> page for the
              full picker built from this pattern.
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}

export function DropdownDemo() {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative inline-flex">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex cursor-pointer items-center gap-2 rounded-full border border-v-line bg-white px-3.5 py-2 text-sm font-medium hover:border-v-accent"
      >
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-v-accent-deep text-[10px] font-semibold text-white">
          RS
        </span>
        Roopan
        <span className="text-[10px] text-v-muted">▲</span>
      </button>
      {open ? (
        <div className="animate-v-pop absolute bottom-[calc(100%+8px)] left-0 z-50 w-64 overflow-hidden rounded-v-sm border border-v-line bg-white shadow-[0_18px_50px_rgba(11,11,12,.16)]">
          <div className="flex flex-col p-1.5">
            {["Account & profile", "Members & invites", "Appearance"].map((item) => (
              <button
                key={item}
                className="cursor-pointer rounded-v-sm px-2.5 py-2 text-left text-[13.5px] hover:bg-v-soft"
              >
                {item}
              </button>
            ))}
          </div>
          <div className="border-t border-v-line p-1.5">
            <button className="w-full cursor-pointer rounded-v-sm px-2.5 py-2 text-left text-[13.5px] text-v-danger hover:bg-v-soft">
              Sign out
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
