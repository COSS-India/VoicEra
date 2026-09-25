"use client";

import { useMemo, type ReactNode } from "react";
import { LanguageConfigList } from "@/components/wizard/LanguageConfigList";
import type { StackEditorSection } from "@/components/wizard/LanguageStackEditor";
import type { LanguageStack } from "@/lib/language-stacks";
import type { WizardCatalogs } from "@/lib/use-wizard-catalogs";

export type StackFieldsSection = "languages" | "llm" | "stt" | "tts";

const ALL_SECTIONS: StackFieldsSection[] = ["languages", "llm", "stt", "tts"];

interface AgentStackFieldsProps {
  langs: string[];
  primaryLang: string;
  languageStacks: Record<string, LanguageStack>;
  activeLang: string;
  onLangsChange: (langs: string[]) => void;
  onPrimaryLangChange: (lang: string) => void;
  onActiveLangChange: (lang: string) => void;
  onStackChange: (lang: string, patch: Partial<LanguageStack>) => void;
  catalogs: WizardCatalogs;
  sections?: StackFieldsSection[];
  allowMultipleExpanded?: boolean;
  trailing?: ReactNode;
}

function stackSectionsFromProps(sections: StackFieldsSection[]): StackEditorSection[] {
  const out: StackEditorSection[] = [];
  if (sections.includes("stt")) out.push("stt");
  if (sections.includes("llm")) out.push("llm");
  if (sections.includes("tts")) out.push("tts");
  return out;
}

/**
 * Language accordion + per-language STT/TTS/LLM stacks for the wizard and edit page.
 */
export function AgentStackFields({
  langs,
  primaryLang,
  languageStacks,
  activeLang,
  onLangsChange,
  onPrimaryLangChange,
  onActiveLangChange,
  onStackChange,
  catalogs,
  sections = ALL_SECTIONS,
  allowMultipleExpanded,
  trailing,
}: AgentStackFieldsProps) {
  const selectableLanguages = useMemo(() => {
    const merged = { ...catalogs.availableLanguages };
    for (const id of langs) {
      if (!merged[id] && catalogs.languages[id]) merged[id] = catalogs.languages[id];
    }
    return merged;
  }, [catalogs.availableLanguages, catalogs.languages, langs]);

  const showLanguageConfig =
    sections.includes("languages") ||
    sections.includes("stt") ||
    sections.includes("llm") ||
    sections.includes("tts");

  const stackSections = stackSectionsFromProps(sections);

  return (
    <div className="flex flex-col gap-5">
      {showLanguageConfig ? (
        <LanguageConfigList
            langs={langs}
            primaryLang={primaryLang}
            languageStacks={languageStacks}
            activeLang={activeLang}
            onLangsChange={onLangsChange}
            onPrimaryLangChange={onPrimaryLangChange}
            onActiveLangChange={onActiveLangChange}
            onStackChange={onStackChange}
            catalogs={catalogs}
            selectableLanguages={selectableLanguages}
            stackSections={stackSections}
            allowMultipleExpanded={allowMultipleExpanded}
            disabled={catalogs.loading || catalogs.languagesLoading}
          />
      ) : null}

      {trailing}
    </div>
  );
}
