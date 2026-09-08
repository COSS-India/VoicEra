"use client";

import { useState } from "react";

interface SwitchProps {
  checked: boolean;
  label?: string;
  onChange?: (checked: boolean) => void;
  disabled?: boolean;
}

/** Fully controlled — always reflects `checked`, so it stays in sync when the
 * underlying value changes elsewhere (loading an agent, applying a template). */
export function Switch({ checked, label, onChange, disabled }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange?.(!checked)}
      className={`relative h-6 w-11 shrink-0 rounded-full transition-colors duration-200 ease-out ${
        disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer"
      } ${checked ? "bg-v-accent" : "bg-v-line-strong"}`}
    >
      <span
        className={`absolute top-0.5 left-0.5 h-5 w-5 rounded-full bg-white shadow transition-transform duration-200 ${
          checked ? "translate-x-5" : "translate-x-0"
        }`}
        style={{ transitionTimingFunction: "cubic-bezier(0.34, 1.56, 0.64, 1)" }}
      />
    </button>
  );
}

/** Self-contained demo for the component gallery — manages its own checked state. */
export function SwitchDemo({ defaultChecked = false, label }: { defaultChecked?: boolean; label?: string }) {
  const [checked, setChecked] = useState(defaultChecked);
  return <Switch checked={checked} label={label} onChange={setChecked} />;
}
