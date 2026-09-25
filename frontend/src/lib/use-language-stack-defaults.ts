"use client";

import { useEffect, type Dispatch, type SetStateAction } from "react";
import {
  activeLanguageStack,
  patchLanguageStack,
  type LanguageStack,
} from "@/lib/language-stacks";
import type { AgentForm } from "@/lib/wizard-data";
import {
  defaultModelFromSettings,
  modelOptionsFromSettings,
  pickFirstProvider,
  voiceOptionsFromSettings,
  type WizardCatalogs,
} from "@/lib/use-wizard-catalogs";

function providerStillValid(list: Record<string, unknown>, id: string): boolean {
  return Boolean(id && id in list);
}

function applyStackDefaults(
  stack: LanguageStack,
  catalogs: WizardCatalogs,
  lang: string,
): LanguageStack {
  let next = { ...stack };

  if (!providerStillValid(catalogs.sttProviders, next.sttProvider)) {
    next = { ...next, sttProvider: pickFirstProvider(catalogs.sttProviders) };
  }
  if (!providerStillValid(catalogs.ttsProviders, next.ttsProvider)) {
    next = { ...next, ttsProvider: pickFirstProvider(catalogs.ttsProviders) };
  }
  if (!providerStillValid(catalogs.llmProviders, next.llmProvider)) {
    next = { ...next, llmProvider: pickFirstProvider(catalogs.llmProviders) };
  }

  // Settings lag a provider (or active language) change until the fetch for the
  // new provider lands; applying the previous provider's catalog would swap in
  // a model id this stack's provider never served.
  if (catalogs.llmSettings && catalogs.llmSettings.provider === next.llmProvider) {
    const model = defaultModelFromSettings(catalogs.llmSettings);
    const models = modelOptionsFromSettings(catalogs.llmSettings);
    if (model && !next.llmModel) {
      next = { ...next, llmModel: model };
    } else if (
      // A connection-based provider's model ids come from the chosen endpoint,
      // not the catalog, so the catalog cannot judge them.
      !catalogs.llmSettings.connection_based &&
      next.llmModel &&
      !models.some((m) => m.value === next.llmModel) &&
      models[0]
    ) {
      next = { ...next, llmModel: models[0]!.value };
    }
  }

  if (catalogs.sttSettings && catalogs.sttSettings.provider === next.sttProvider) {
    const model = defaultModelFromSettings(catalogs.sttSettings);
    const models = modelOptionsFromSettings(catalogs.sttSettings);
    if (model && !next.sttModel) {
      next = { ...next, sttModel: model };
    } else if (next.sttModel && !models.some((m) => m.value === next.sttModel) && models[0]) {
      next = { ...next, sttModel: models[0]!.value };
    }
  }

  if (catalogs.ttsSettings && catalogs.ttsSettings.provider === next.ttsProvider) {
    const model = defaultModelFromSettings(catalogs.ttsSettings);
    const models = modelOptionsFromSettings(catalogs.ttsSettings);
    if (model && !next.ttsModel) {
      next = { ...next, ttsModel: model };
    } else if (next.ttsModel && !models.some((m) => m.value === next.ttsModel) && models[0]) {
      next = { ...next, ttsModel: models[0]!.value };
    }

    const voices = voiceOptionsFromSettings(catalogs.ttsSettings, next.ttsModel, lang);
    if (voices.length > 0 && (!next.voice || !voices.some((v) => v.id === next.voice))) {
      next = { ...next, voice: voices[0]!.id };
    }
  }

  return next;
}

/**
 * Auto-pick providers/models/voice for the **active** language stack when
 * catalogs load or the active language changes.
 */
export function useLanguageStackDefaults(
  form: AgentForm,
  catalogs: WizardCatalogs,
  setForm: Dispatch<SetStateAction<AgentForm>>,
) {
  const activeLang = form.activeLang || form.primaryLang || form.langs[0] || "";
  const activeStack = activeLanguageStack(form);

  useEffect(() => {
    if (catalogs.loading || !activeLang || form.langs.length === 0) return;

    setForm((f) => {
      const lang = f.activeLang || f.primaryLang || f.langs[0] || "";
      if (!lang) return f;
      const current = f.languageStacks[lang];
      if (!current) return f;

      const updated = applyStackDefaults(current, catalogs, lang);
      if (JSON.stringify(updated) === JSON.stringify(current)) return f;

      return {
        ...f,
        languageStacks: patchLanguageStack(f.languageStacks, lang, updated),
      };
    });
  }, [
    catalogs.loading,
    catalogs.sttProviders,
    catalogs.ttsProviders,
    catalogs.llmProviders,
    catalogs.sttSettings,
    catalogs.ttsSettings,
    catalogs.llmSettings,
    activeLang,
    activeStack.sttProvider,
    activeStack.ttsProvider,
    activeStack.llmProvider,
    form.langs.length,
    setForm,
  ]);
}
