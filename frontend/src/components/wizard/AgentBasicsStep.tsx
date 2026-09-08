"use client";

import { NameStep } from "@/components/wizard/NameStep";
import { PromptKnowledgeStep } from "@/components/wizard/PromptKnowledgeStep";
import type { AgentForm } from "@/lib/wizard-data";

interface AgentBasicsStepProps {
  form: AgentForm;
  onChange: <K extends keyof AgentForm>(key: K, value: AgentForm[K]) => void;
  onOpenLibrary: () => void;
  onNotify: (title: string, note: string) => void;
}

/** Name, greeting, and prompt & knowledge base converged into one step — they're
 * all "who this agent is and what it says", so splitting them across separate
 * pages was more clicking than the content warranted. Composes the two
 * existing step components rather than duplicating their fields. */
export function AgentBasicsStep({ form, onChange, onOpenLibrary, onNotify }: AgentBasicsStepProps) {
  return (
    <div className="flex flex-col gap-8 animate-v-rise">
      <NameStep form={form} onChange={onChange} />
      <div className="border-t border-v-line" />
      <PromptKnowledgeStep form={form} onChange={onChange} onOpenLibrary={onOpenLibrary} onNotify={onNotify} />
    </div>
  );
}
