"use client";

import type { Dispatch, SetStateAction } from "react";
import { AgentStackFields } from "@/components/wizard/AgentStackFields";
import { patchLanguageStack, syncLanguageStacks, type LanguageStack } from "@/lib/language-stacks";
import type { AgentForm } from "@/lib/wizard-data";
import type { WizardCatalogs } from "@/lib/use-wizard-catalogs";

interface LanguageProvidersStepProps {
  form: AgentForm;
  setForm: Dispatch<SetStateAction<AgentForm>>;
  catalogs: WizardCatalogs;
}

export function LanguageProvidersStep({ form, setForm, catalogs }: LanguageProvidersStepProps) {
  const handleLangsChange = (langs: string[]) => {
    setForm((f) => {
      let primaryLang = f.primaryLang;
      if (langs.length === 0) {
        primaryLang = "";
      } else if (!primaryLang || !langs.includes(primaryLang)) {
        primaryLang = langs[0];
      }
      const synced = syncLanguageStacks(langs, f.languageStacks, f.activeLang, primaryLang);
      return {
        ...f,
        langs,
        primaryLang: synced.primaryLang,
        languageStacks: synced.languageStacks,
        activeLang: synced.activeLang,
      };
    });
  };

  const handlePrimaryLangChange = (lang: string) => {
    setForm((f) => ({ ...f, primaryLang: lang }));
  };

  const handleStackChange = (lang: string, patch: Partial<LanguageStack>) => {
    setForm((f) => ({
      ...f,
      languageStacks: patchLanguageStack(f.languageStacks, lang, patch),
    }));
  };

  return (
    <div className="flex flex-col gap-6">
      <AgentStackFields
        langs={form.langs}
        primaryLang={form.primaryLang}
        languageStacks={form.languageStacks}
        activeLang={form.activeLang}
        onLangsChange={handleLangsChange}
        onPrimaryLangChange={handlePrimaryLangChange}
        onActiveLangChange={(lang) => setForm((f) => ({ ...f, activeLang: lang }))}
        onStackChange={handleStackChange}
        catalogs={catalogs}
        sections={["languages", "llm", "stt", "tts"]}
      />
    </div>
  );
}
