"use client";

import { AgentStackFields } from "@/components/wizard/AgentStackFields";
import type { AgentForm } from "@/lib/wizard-data";
import type { WizardCatalogs } from "@/lib/use-wizard-catalogs";

interface LanguageProvidersStepProps {
  form: AgentForm;
  catalogs: WizardCatalogs;
  onChange: <K extends keyof AgentForm>(key: K, value: AgentForm[K]) => void;
}

export function LanguageProvidersStep({ form, catalogs, onChange }: LanguageProvidersStepProps) {
  return (
    <div className="flex flex-col gap-6 animate-v-rise">
      <AgentStackFields
        value={form}
        onChange={(key, value) => onChange(key, value as AgentForm[typeof key])}
        catalogs={catalogs}
        sections={["languages", "llm", "stt", "tts"]}
      />
    </div>
  );
}
