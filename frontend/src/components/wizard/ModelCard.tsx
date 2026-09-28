"use client";

import {
  LanguageStackEditor,
  type StackEditorSection,
} from "@/components/wizard/LanguageStackEditor";
import type { LanguageStack } from "@/lib/language-stacks";
import type { WizardCatalogs } from "@/lib/use-wizard-catalogs";
import { languageLabel } from "@/lib/use-wizard-catalogs";

export interface ModelCardProps {
  lang: string;
  stack: LanguageStack;
  catalogs: WizardCatalogs;
  onStackChange: (patch: Partial<LanguageStack>) => void;
  sections?: StackEditorSection[];
  catalogsLoading?: boolean;
}

/** STT / LLM / TTS settings for the active language. */
export function ModelCard({
  lang,
  stack,
  catalogs,
  onStackChange,
  sections = ["stt", "llm", "tts"],
  catalogsLoading = false,
}: ModelCardProps) {
  const label = languageLabel(catalogs.languages, lang) || lang;

  return (
    <div
      id={`language-stack-${lang}`}
      role="tabpanel"
      aria-labelledby={`language-tab-${lang}`}
      className="flex flex-col gap-4"
      data-testid={`model-card-${lang}`}
    >
      <LanguageStackEditor
        lang={lang}
        stack={stack}
        catalogs={catalogs}
        onStackChange={onStackChange}
        sections={sections}
        catalogsLoading={catalogsLoading}
      />
    </div>
  );
}
