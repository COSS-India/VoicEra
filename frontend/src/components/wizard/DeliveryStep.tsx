"use client";

import { Monitor, Phone } from "lucide-react";
import type { AgentForm } from "@/lib/wizard-data";
import type { WizardCatalogs } from "@/lib/use-wizard-catalogs";

interface DeliveryStepProps {
  form: AgentForm;
  catalogs: WizardCatalogs;
  onChange: <K extends keyof AgentForm>(key: K, value: AgentForm[K]) => void;
}

const TELEPHONY_OPTIONS = [
  { id: "plivo", name: "Plivo", note: "Real phone number via Plivo." },
  { id: "vobiz", name: "Vobiz", note: "Real phone number via Vobiz." },
];

function DeliveryCard({
  name,
  note,
  icon: Icon,
  selected,
  disabled,
  onClick,
}: {
  name: string;
  note: string;
  icon: typeof Phone;
  selected: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className={`flex flex-col items-start gap-3 rounded-v-md border p-5 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
        selected ? "border-v-accent bg-v-pale/40" : "border-v-line bg-white hover:border-v-accent"
      }`}
    >
      <span
        className={`flex h-10 w-10 items-center justify-center rounded-full ${
          selected ? "bg-v-accent text-white" : "bg-v-soft text-v-fg"
        }`}
      >
        <Icon className="size-4" strokeWidth={1.8} />
      </span>
      <span className="flex flex-col gap-1">
        <span className="text-[15px] font-semibold tracking-tight">{name}</span>
        <span className="text-[12.5px] font-light leading-relaxed text-v-muted">{note}</span>
      </span>
      <span
        className={`mt-1 font-mono text-[10px] uppercase tracking-[.1em] ${
          selected ? "text-v-accent" : "text-transparent"
        }`}
      >
        Selected
      </span>
    </button>
  );
}

/** Delivery gets its own three-card step (not a dropdown) because unlike an
 * LLM/model pick, it decides whether this agent even has a real phone number
 * — a bigger decision that deserves more visual weight. */
export function DeliveryStep({ form, catalogs, onChange }: DeliveryStepProps) {
  return (
    <div className="flex flex-col gap-6 animate-v-rise">
      <p className="text-[13px] font-light text-v-muted">
        How will callers reach this agent? Pick a telephony provider for a real number, or stay on a browser
        WebSocket for testing.
      </p>

      <div data-tour="delivery-options" className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {TELEPHONY_OPTIONS.map((opt) => {
          const provider = catalogs.telephonyProviders[opt.id];
          const configured = Boolean(provider);
          return (
            <DeliveryCard
              key={opt.id}
              name={provider?.name ?? opt.name}
              note={configured ? opt.note : "Not configured — add it under Integrations first."}
              icon={Phone}
              selected={form.delivery === opt.id}
              disabled={!configured}
              onClick={() => onChange("delivery", opt.id)}
            />
          );
        })}
        <DeliveryCard
          name="WebSocket"
          note="Browser microphone test call — no phone number needed."
          icon={Monitor}
          selected={form.delivery === ""}
          onClick={() => onChange("delivery", "")}
        />
      </div>
    </div>
  );
}
