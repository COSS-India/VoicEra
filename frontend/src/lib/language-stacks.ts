/** Per-language STT / TTS / LLM stack — mirrors `config.language_models[lang]`. */

import type { ProviderSettingsCatalog } from "@/lib/catalog-types";
import { modelConfigFromSettings } from "@/lib/catalog-utils";
import type { AgentForm } from "@/lib/wizard-data";
import { getLlmSettings, getSttSettings, getTtsSettings } from "@/lib/api-client";

export interface LanguageStack {
  sttProvider: string;
  sttModel: string;
  sttExtra: Record<string, unknown>;
  ttsProvider: string;
  ttsModel: string;
  ttsExtra: Record<string, unknown>;
  voice: string;
  llmProvider: string;
  llmModel: string;
  llmExtra: Record<string, unknown>;
}

export const EMPTY_LANGUAGE_STACK: LanguageStack = {
  sttProvider: "",
  sttModel: "",
  sttExtra: {},
  ttsProvider: "",
  ttsModel: "",
  ttsExtra: {},
  voice: "",
  llmProvider: "",
  llmModel: "",
  llmExtra: {},
};

const STACK_CONFIG_OMIT = {
  stt: new Set(["provider", "model", "language"]),
  tts: new Set(["provider", "model", "language", "voice"]),
  llm: new Set(["provider", "model", "language"]),
} as const;

/** Build a wizard stack slice from saved API configs. */
export function stackFromApiConfigs(
  stt: Record<string, unknown>,
  tts: Record<string, unknown>,
  llm: Record<string, unknown>,
): LanguageStack {
  return {
    sttProvider: String(stt.provider ?? ""),
    sttModel: String(stt.model ?? ""),
    sttExtra: Object.fromEntries(
      Object.entries(stt).filter(([key]) => !STACK_CONFIG_OMIT.stt.has(key)),
    ),
    ttsProvider: String(tts.provider ?? ""),
    ttsModel: String(tts.model ?? ""),
    voice: String(tts.voice ?? ""),
    ttsExtra: Object.fromEntries(
      Object.entries(tts).filter(([key]) => !STACK_CONFIG_OMIT.tts.has(key)),
    ),
    llmProvider: String(llm.provider ?? ""),
    llmModel: String(llm.model ?? ""),
    llmExtra: Object.fromEntries(
      Object.entries(llm).filter(([key]) => !STACK_CONFIG_OMIT.llm.has(key)),
    ),
  };
}

export function cloneLanguageStack(stack: LanguageStack): LanguageStack {
  return {
    ...stack,
    sttExtra: { ...stack.sttExtra },
    ttsExtra: { ...stack.ttsExtra },
    llmExtra: { ...stack.llmExtra },
  };
}

/** Resolve the stack currently being edited. */
export function activeLanguageStack(
  form: Pick<AgentForm, "langs" | "activeLang" | "primaryLang" | "languageStacks">,
): LanguageStack {
  const lang = form.activeLang || form.primaryLang || form.langs[0] || "";
  if (lang && form.languageStacks[lang]) {
    return form.languageStacks[lang]!;
  }
  return EMPTY_LANGUAGE_STACK;
}

export function isLanguageStackReady(stack: LanguageStack): boolean {
  return Boolean(
    stack.sttProvider &&
      stack.ttsProvider &&
      stack.llmProvider &&
      stack.llmModel,
  );
}

export function allLanguageStacksReady(form: Pick<AgentForm, "langs" | "languageStacks">): boolean {
  if (form.langs.length === 0) return false;
  return form.langs.every((lang) => {
    const stack = form.languageStacks[lang];
    return stack ? isLanguageStackReady(stack) : false;
  });
}

/**
 * Keep `languageStacks` aligned with `langs`: add missing entries (seeded from
 * primary), drop removed languages, and ensure `activeLang` is valid.
 */
export function syncLanguageStacks(
  langs: string[],
  stacks: Record<string, LanguageStack>,
  activeLang: string,
  primaryLang: string,
): { languageStacks: Record<string, LanguageStack>; activeLang: string; primaryLang: string } {
  const primary = langs.includes(primaryLang) ? primaryLang : (langs[0] ?? "");
  const primaryStack = (primary && stacks[primary]) || EMPTY_LANGUAGE_STACK;
  const nextStacks: Record<string, LanguageStack> = {};

  for (const lang of langs) {
    if (stacks[lang]) {
      nextStacks[lang] = stacks[lang]!;
    } else {
      nextStacks[lang] = cloneLanguageStack(primaryStack);
    }
  }

  let nextActive = activeLang;
  if (!langs.includes(nextActive)) {
    nextActive = primary;
  }

  return { languageStacks: nextStacks, activeLang: nextActive, primaryLang: primary };
}

export function patchLanguageStack(
  stacks: Record<string, LanguageStack>,
  lang: string,
  patch: Partial<LanguageStack>,
): Record<string, LanguageStack> {
  const current = stacks[lang] ?? EMPTY_LANGUAGE_STACK;
  return {
    ...stacks,
    [lang]: {
      ...current,
      ...patch,
      sttExtra: patch.sttExtra ?? current.sttExtra,
      ttsExtra: patch.ttsExtra ?? current.ttsExtra,
      llmExtra: patch.llmExtra ?? current.llmExtra,
    },
  };
}

export interface SaveCatalogs {
  sttByProvider: Record<string, ProviderSettingsCatalog>;
  ttsByProvider: Record<string, ProviderSettingsCatalog>;
  llmByProvider: Record<string, ProviderSettingsCatalog>;
}

function configFromStack(
  stack: LanguageStack,
  kind: "stt" | "tts" | "llm",
  lang: string,
  catalog: ProviderSettingsCatalog | undefined,
): Record<string, unknown> | null {
  const provider =
    kind === "stt" ? stack.sttProvider : kind === "tts" ? stack.ttsProvider : stack.llmProvider;
  const model = kind === "stt" ? stack.sttModel : kind === "tts" ? stack.ttsModel : stack.llmModel;
  const extra =
    kind === "stt" ? stack.sttExtra : kind === "tts" ? stack.ttsExtra : stack.llmExtra;

  if (!provider || !model) return null;

  if (catalog && catalog.provider === provider) {
    return modelConfigFromSettings(catalog, model, {
      ...extra,
      ...(kind !== "llm" ? { language: lang } : {}),
      ...(kind === "tts" && stack.voice ? { voice: stack.voice } : {}),
    });
  }

  return {
    provider,
    model,
    ...(kind !== "llm" ? { language: lang } : {}),
    ...(kind === "tts" && stack.voice ? { voice: stack.voice } : {}),
    ...extra,
  };
}

/** Build API configs for one language stack using per-provider catalogs. */
export function buildConfigsForLanguageStack(
  lang: string,
  stack: LanguageStack,
  catalogs: SaveCatalogs,
): {
  stt: Record<string, unknown> | null;
  tts: Record<string, unknown> | null;
  llm: Record<string, unknown> | null;
} {
  return {
    stt: configFromStack(stack, "stt", lang, catalogs.sttByProvider[stack.sttProvider]),
    tts: configFromStack(stack, "tts", lang, catalogs.ttsByProvider[stack.ttsProvider]),
    llm: configFromStack(stack, "llm", lang, catalogs.llmByProvider[stack.llmProvider]),
  };
}

/** Fetch provider settings catalogs for every provider referenced in `languageStacks`. */
export async function resolveSaveCatalogs(form: Pick<AgentForm, "langs" | "languageStacks">): Promise<SaveCatalogs> {
  const sttProviders = new Set<string>();
  const ttsProviders = new Set<string>();
  const llmProviders = new Set<string>();

  for (const lang of form.langs) {
    const stack = form.languageStacks[lang];
    if (!stack) continue;
    if (stack.sttProvider) sttProviders.add(stack.sttProvider);
    if (stack.ttsProvider) ttsProviders.add(stack.ttsProvider);
    if (stack.llmProvider) llmProviders.add(stack.llmProvider);
  }

  const [sttEntries, ttsEntries, llmEntries] = await Promise.all([
    Promise.all(
      [...sttProviders].map(async (provider) => [provider, await getSttSettings(provider, form.langs)] as const),
    ),
    Promise.all(
      [...ttsProviders].map(async (provider) => [provider, await getTtsSettings(provider, form.langs)] as const),
    ),
    Promise.all([...llmProviders].map(async (provider) => [provider, await getLlmSettings(provider)] as const)),
  ]);

  return {
    sttByProvider: Object.fromEntries(sttEntries),
    ttsByProvider: Object.fromEntries(ttsEntries),
    llmByProvider: Object.fromEntries(llmEntries),
  };
}
