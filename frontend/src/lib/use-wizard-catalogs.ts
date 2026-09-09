"use client";

import { useEffect, useMemo, useState } from "react";
import {
  getLanguages,
  getLlmSettings,
  getSttSettings,
  getTtsSettings,
  listLlmProviders,
  listSttProviders,
  listTelephonyProviders,
  listTtsProviders,
} from "@/lib/api-client";
import type { LanguagesMap, ProviderList, ProviderSettingsCatalog } from "@/lib/catalog-types";
import {
  defaultModelId,
  modelConfigFromSettings,
  modelIds,
  providerLabelWithType,
  providerLanguageIds,
  resolvedField,
  selectOptionsFromField,
} from "@/lib/catalog-utils";

export const WEBSOCKET_DELIVERY = "websocket";

export interface WizardCatalogs {
  languages: LanguagesMap;
  /** Subset of `languages` actually supported by authenticated STT/TTS providers. */
  availableLanguages: LanguagesMap;
  languagesLoading: boolean;
  /** Full STT/TTS/LLM lists from /configuration/* — includes unauthenticated entries. */
  sttProviders: ProviderList;
  ttsProviders: ProviderList;
  llmProviders: ProviderList;
  telephonyProviders: ProviderList;
  sttSettings: ProviderSettingsCatalog | null;
  ttsSettings: ProviderSettingsCatalog | null;
  llmSettings: ProviderSettingsCatalog | null;
  loading: boolean;
  error: string;
}

/** Keep only providers the org can actually use (`authenticated: true`). */
function filterToAuthenticated(list: ProviderList): ProviderList {
  return Object.fromEntries(Object.entries(list).filter(([, p]) => p.authenticated === true));
}

export function useWizardCatalogs(
  langIds: string[],
  sttProvider: string,
  ttsProvider: string,
  llmProvider: string,
): WizardCatalogs {
  const [languages, setLanguages] = useState<LanguagesMap>({});
  const [availableLanguages, setAvailableLanguages] = useState<LanguagesMap>({});
  const [languagesLoading, setLanguagesLoading] = useState(true);
  const [sttProviders, setSttProviders] = useState<ProviderList>({});
  const [ttsProviders, setTtsProviders] = useState<ProviderList>({});
  const [llmProviders, setLlmProviders] = useState<ProviderList>({});
  const [telephonyProviders, setTelephonyProviders] = useState<ProviderList>({});
  const [sttSettings, setSttSettings] = useState<ProviderSettingsCatalog | null>(null);
  const [ttsSettings, setTtsSettings] = useState<ProviderSettingsCatalog | null>(null);
  const [llmSettings, setLlmSettings] = useState<ProviderSettingsCatalog | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const langKey = langIds.join(",");

  // Re-fetched every time the selected language(s) change — hitting the STT/TTS
  // list endpoints with the current language filter keeps the pickers scoped to
  // providers usable for this language. Authenticated vs not is a per-entry flag
  // on the response (no /auth/catalog call from the wizard).
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    Promise.all([
      getLanguages(),
      listSttProviders(langIds),
      listTtsProviders(langIds),
      listLlmProviders(),
      listTelephonyProviders(),
    ])
      .then(([langsRes, stt, tts, llm, tel]) => {
        if (cancelled) return;
        setLanguages(langsRes.languages);
        setSttProviders(stt);
        setTtsProviders(tts);
        setLlmProviders(llm);
        // Delivery only offers providers that can actually place a call.
        setTelephonyProviders(filterToAuthenticated(tel));
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load catalogs.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // langKey is the stable derived form of langIds — depending on the array
    // itself would refire this on every render callers pass a fresh literal
    // (e.g. AgentTestModal recomputing `langs` each render during a live call).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [langKey]);

  // Derive which languages are actually usable by reading each authenticated
  // STT/TTS provider's declared language support from settings — nothing hardcoded.
  useEffect(() => {
    if (Object.keys(languages).length === 0) {
      setAvailableLanguages({});
      setLanguagesLoading(true);
      return;
    }
    let cancelled = false;
    setLanguagesLoading(true);
    (async () => {
      try {
        const [allStt, allTts] = await Promise.all([listSttProviders([]), listTtsProviders([])]);
        const authenticatedStt = Object.keys(allStt).filter((id) => allStt[id]?.authenticated);
        const authenticatedTts = Object.keys(allTts).filter((id) => allTts[id]?.authenticated);
        if (authenticatedStt.length === 0 && authenticatedTts.length === 0) {
          if (!cancelled) {
            setAvailableLanguages({});
            setLanguagesLoading(false);
          }
          return;
        }
        const settings = await Promise.all([
          ...authenticatedStt.map((id) => getSttSettings(id, []).catch(() => null)),
          ...authenticatedTts.map((id) => getTtsSettings(id, []).catch(() => null)),
        ]);
        const codes = new Set<string>();
        for (const s of settings) {
          for (const id of providerLanguageIds(s)) codes.add(id);
        }
        if (cancelled) return;
        setAvailableLanguages(
          codes.size > 0
            ? Object.fromEntries(Object.entries(languages).filter(([id]) => codes.has(id)))
            : languages,
        );
      } catch {
        if (!cancelled) setAvailableLanguages(languages);
      } finally {
        if (!cancelled) setLanguagesLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [languages]);

  useEffect(() => {
    if (!sttProvider) {
      setSttSettings(null);
      return;
    }
    let cancelled = false;
    getSttSettings(sttProvider, langIds)
      .then((s) => {
        if (!cancelled) setSttSettings(s);
      })
      .catch(() => {
        if (!cancelled) setSttSettings(null);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sttProvider, langKey]);

  useEffect(() => {
    if (!ttsProvider) {
      setTtsSettings(null);
      return;
    }
    let cancelled = false;
    getTtsSettings(ttsProvider, langIds)
      .then((s) => {
        if (!cancelled) setTtsSettings(s);
      })
      .catch(() => {
        if (!cancelled) setTtsSettings(null);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ttsProvider, langKey]);

  useEffect(() => {
    if (!llmProvider) {
      setLlmSettings(null);
      return;
    }
    let cancelled = false;
    getLlmSettings(llmProvider)
      .then((s) => {
        if (!cancelled) setLlmSettings(s);
      })
      .catch(() => {
        if (!cancelled) setLlmSettings(null);
      });
    return () => {
      cancelled = true;
    };
  }, [llmProvider]);

  return useMemo(
    () => ({
      languages,
      availableLanguages,
      languagesLoading,
      sttProviders,
      ttsProviders,
      llmProviders,
      telephonyProviders,
      sttSettings,
      ttsSettings,
      llmSettings,
      loading,
      error,
    }),
    [
      languages,
      availableLanguages,
      languagesLoading,
      sttProviders,
      ttsProviders,
      llmProviders,
      telephonyProviders,
      sttSettings,
      ttsSettings,
      llmSettings,
      loading,
      error,
    ],
  );
}

export function providerOptions(list: ProviderList) {
  return Object.values(list).map((p) => ({
    value: p.provider,
    label: p.name || p.provider,
  }));
}

/** Every provider from /configuration/{kind}, sorted by name, with
 * unauthenticated ones marked `disabled` (and labeled "(Not configured)") —
 * so pickers show the full catalog but only authenticated entries are selectable.
 * Provider type is passed separately for a badge, not baked into the label. */
export function searchableProviderOptions(list: ProviderList) {
  return Object.values(list)
    .map((p) => {
      const disabled = p.authenticated !== true;
      const name = p.name || p.provider;
      return {
        value: p.provider,
        label: disabled ? `${name} (Not configured)` : name,
        providerType: p.provider_type,
        disabled,
      };
    })
    .sort((a, b) => a.label.localeCompare(b.label));
}

export function languageChipOptions(languages: LanguagesMap): string[] {
  return Object.entries(languages).map(([id, label]) => `${label}|${id}`);
}

export function parseLanguageChip(chip: string): string {
  const parts = chip.split("|");
  return parts.length > 1 ? parts[parts.length - 1]! : chip;
}

export function languageLabel(languages: LanguagesMap, id: string): string {
  return languages[id] ?? id;
}

export function telephonyOptions(telephony: ProviderList) {
  return [
    { value: "", label: "WebSocket — browser test (default)" },
    ...Object.values(telephony).map((p) => ({
      value: p.provider,
      label: `${providerLabelWithType(p.name || p.provider, p.provider_type)} — telephony`,
    })),
  ];
}

/** @deprecated use telephonyOptions */
export function deliveryOptions(telephony: ProviderList) {
  return telephonyOptions(telephony);
}

export function buildModelConfigsFromCatalogs(
  catalogs: Pick<WizardCatalogs, "sttSettings" | "ttsSettings" | "llmSettings">,
  overrides: {
    llmModel?: string;
    sttModel?: string;
    ttsModel?: string;
    voice?: string;
    primaryLang?: string;
    /** Per-model field overrides picked in the wizard (e.g. temperature,
     * max_tokens, base_url) — only keys that belong to the selected model are
     * ever applied; anything left over from a previously-selected model is
     * silently ignored (see `modelConfigFromSettings`). */
    sttExtra?: Record<string, unknown>;
    ttsExtra?: Record<string, unknown>;
    llmExtra?: Record<string, unknown>;
  },
) {
  const sttModelId = overrides.sttModel || defaultModelFromSettings(catalogs.sttSettings);
  const ttsModelId = overrides.ttsModel || defaultModelFromSettings(catalogs.ttsSettings);
  const llmModelId = overrides.llmModel || defaultModelFromSettings(catalogs.llmSettings);

  // `primaryLang` is canonical (e.g. `hi`); `modelConfigFromSettings` maps it
  // to the vendor wire code on `stt`/`tts`.language while resolving knobs by
  // canonical id.
  const stt =
    catalogs.sttSettings && sttModelId
      ? modelConfigFromSettings(catalogs.sttSettings, sttModelId, {
          ...(overrides.sttExtra ?? {}),
          ...(overrides.primaryLang ? { language: overrides.primaryLang } : {}),
        })
      : null;
  const tts =
    catalogs.ttsSettings && ttsModelId
      ? modelConfigFromSettings(catalogs.ttsSettings, ttsModelId, {
          ...(overrides.ttsExtra ?? {}),
          ...(overrides.primaryLang ? { language: overrides.primaryLang } : {}),
          ...(overrides.voice ? { voice: overrides.voice } : {}),
        })
      : null;
  const llm =
    catalogs.llmSettings && llmModelId
      ? modelConfigFromSettings(catalogs.llmSettings, llmModelId, { ...(overrides.llmExtra ?? {}) })
      : null;
  return { stt, tts, llm };
}

export function defaultModelFromSettings(settings: ProviderSettingsCatalog | null): string {
  return defaultModelId(settings);
}

/** `modelId`/`languageId` pick which (model, language) pair's voice field to
 * read — voice options can vary per model and, via `capabilities`, per language. */
export function voiceOptionsFromSettings(
  settings: ProviderSettingsCatalog | null,
  modelId?: string,
  languageId?: string,
) {
  const voiceField = resolvedField(settings, modelId || defaultModelId(settings), languageId, "voice");
  if (!voiceField) return [];
  return selectOptionsFromField(voiceField).map((o) => ({
    id: o.value,
    name: o.label,
    note: voiceField.description ?? "",
  }));
}

/** True when the given (model, language)'s voice field is a free-text id (e.g. Cartesia's voice UUID) rather than a pick-list. */
export function voiceFieldIsFreeText(
  settings: ProviderSettingsCatalog | null,
  modelId?: string,
  languageId?: string,
): boolean {
  const voiceField = resolvedField(settings, modelId || defaultModelId(settings), languageId, "voice");
  if (!voiceField) return false;
  return !Array.isArray(voiceField.examples) || voiceField.examples.length === 0;
}

/** Model ids for this provider, value === label (`fields.model.examples`). */
export function modelOptionsFromSettings(settings: ProviderSettingsCatalog | null) {
  return modelIds(settings).map((id) => ({ value: id, label: id }));
}

/** The given (model, language)'s voice `CatalogField`, or undefined — for direct
 * rendering (placeholder / description) rather than the option-list shape above. */
export function voiceFieldFromSettings(
  settings: ProviderSettingsCatalog | null,
  modelId?: string,
  languageId?: string,
) {
  return resolvedField(settings, modelId || defaultModelId(settings), languageId, "voice");
}

/** First authenticated provider id, if any — used to auto-pick a usable default. */
export function pickFirstProvider(list: ProviderList): string {
  const authenticated = Object.values(list).find((p) => p.authenticated === true);
  return authenticated?.provider ?? "";
}

// Knowledge base document listing/upload now goes through useKnowledgeBase
// (@/hooks/useKnowledgeBase) directly — the same hook the Knowledge Base page
// itself uses — rather than a separate read-only wizard-local fetch.
