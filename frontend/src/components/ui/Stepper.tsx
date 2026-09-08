"use client";

import { useState } from "react";

export interface StepperStep {
  id: string;
  label: string;
  disabled?: boolean;
}

const DEMO_STEPS: StepperStep[] = [
  { id: "start", label: "Setup" },
  { id: "agent", label: "Instructions" },
  { id: "voice", label: "Voice" },
  { id: "review", label: "Review" },
];

interface StepperProps {
  steps?: StepperStep[];
  activeIndex?: number;
  onStepClick?: (index: number, step: StepperStep) => void;
}

export function Stepper({ steps = DEMO_STEPS, activeIndex, onStepClick }: StepperProps) {
  const [internal, setInternal] = useState(1);
  const active = activeIndex ?? internal;

  return (
    <div className="flex flex-wrap items-center gap-0">
      {steps.map((step, i) => {
        const disabled = step.disabled ?? i > active;
        return (
          <span key={step.id} className="flex items-center">
            <button
              type="button"
              disabled={disabled}
              onClick={() => {
                if (onStepClick) onStepClick(i, step);
                else setInternal(i);
              }}
              className="flex items-center gap-2.5 rounded-full px-3 py-2 disabled:cursor-not-allowed disabled:opacity-40 cursor-pointer"
            >
              <span
                className={`flex h-6 w-6 items-center justify-center rounded-full font-mono text-[10.5px] transition-colors duration-[120ms] ${
                  i <= active
                    ? "bg-v-accent text-white"
                    : "bg-v-soft text-v-muted border border-v-line"
                }`}
              >
                {i + 1}
              </span>
              <span
                className={`rounded-v-sm px-1.5 py-0.5 text-[13px] font-medium transition-colors duration-[120ms] ${
                  i === active ? "bg-v-pale/70 text-v-accent-deep" : "text-v-muted"
                }`}
              >
                {step.label}
              </span>
            </button>
            {i < steps.length - 1 ? (
              <span
                className={`mx-1 h-px w-8 ${i < active ? "bg-v-fg" : "bg-v-line"}`}
              />
            ) : null}
          </span>
        );
      })}
    </div>
  );
}
