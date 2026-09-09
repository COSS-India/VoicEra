import type {
  CapabilitySettingLeaf,
  CatalogField,
  ModelCapability,
  ProviderSettingsCatalog,
} from "@/lib/catalog-types";

const NON_FIELD_KEYS = new Set(["model", "language"]);

/** Every model id this provider's settings form offers — from `fields.model.examples`. */
export function modelIds(settings: ProviderSettingsCatalog | null | undefined): string[] {
  const examples = settings?.fields?.model?.examples;
  return Array.isArray(examples) ? examples.map((m) => String(m)) : [];
}

/** The catalog's default model id — `fields.model.default`, falling back to the first option. */
export function defaultModelId(settings: ProviderSettingsCatalog | null | undefined): string {
  const modelField = settings?.fields?.model;
  if (!modelField) return "";
  if (modelField.default !== undefined && modelField.default !== null) return String(modelField.default);
  return modelIds(settings)[0] ?? "";
}

/** `capabilities[modelId].settings`, keyed by canonical language id — this
 * model's per-language setting overrides (may be `undefined` for providers
 * with no capability data, e.g. most LLMs, or models with none declared). */
function capabilityForModel(
  settings: ProviderSettingsCatalog | null | undefined,
  modelId: string,
): ModelCapability | undefined {
  return settings?.capabilities?.[modelId];
}

const INPUT_TYPE_TO_MODE: Record<NonNullable<CapabilitySettingLeaf["input_type"]>, string> = {
  dropdown: "options",
  both: "both",
  slider: "input",
  input: "input",
};

/** Merge one (model, language)-scoped override from `capabilities` onto its
 * matching flat `fields` entry — the override supplies default/options/min/max
 * for this specific language, the flat field supplies `type` and a fallback
 * for everything the override doesn't set. */
function mergeCapabilityLeaf(base: CatalogField, leaf: CapabilitySettingLeaf | undefined): CatalogField {
  if (!leaf) return base;
  return {
    ...base,
    ...(leaf.default !== undefined ? { default: leaf.default } : {}),
    ...(leaf.minimum !== undefined ? { minimum: leaf.minimum } : {}),
    ...(leaf.maximum !== undefined ? { maximum: leaf.maximum } : {}),
    ...(leaf.description !== undefined ? { description: leaf.description } : {}),
    ...(leaf.options !== undefined ? { examples: leaf.options } : {}),
    // input_mode stays as a coarse fallback for callers that don't know
    // about input_type/allow_custom_input; input_type itself is carried
    // through verbatim so the field renderer can honor dropdown vs. slider
    // vs. both+allow_custom_input exactly as the backend declared it.
    ...(leaf.input_type !== undefined ? { input_mode: INPUT_TYPE_TO_MODE[leaf.input_type], input_type: leaf.input_type } : {}),
    ...(leaf.allow_custom_input !== undefined ? { allow_custom_input: leaf.allow_custom_input } : {}),
  };
}

/** Per-(model, language) capability overlay from the API catalog, if any. */
export function capabilityOverlayForModel(
  settings: ProviderSettingsCatalog | null | undefined,
  modelId: string,
  languageId?: string,
): { lang: string | undefined; overlay: Record<string, CapabilitySettingLeaf> } {
  const capability = capabilityForModel(settings, modelId);
  const byLang = capability?.settings ?? {};
  const lang = languageId && byLang[languageId] ? languageId : Object.keys(byLang)[0];
  return { lang, overlay: lang ? (byLang[lang] ?? {}) : {} };
}

/** Every non-secret field for one (model, language) pair, as `[name, CatalogField]`
 * pairs — the flat `fields` (minus `model`/`language`) with any per-language
 * override from `capabilities` merged on top. Falls back to the flat fields
 * unmodified when this provider/model has no capability data (e.g. LLMs).
 *
 * When capabilities declare fields for this model, only those keys are exposed —
 * flat `fields` can union knobs from every model (e.g. Bhashini parler
 * `description` and orpheus `style` both appear at the top level). */
export function resolvedModelFields(
  settings: ProviderSettingsCatalog | null | undefined,
  modelId: string,
  languageId?: string,
): [string, CatalogField][] {
  if (!settings) return [];
  const baseFields = settings.fields ?? {};
  const { overlay } = capabilityOverlayForModel(settings, modelId, languageId);

  if (Object.keys(overlay).length > 0) {
    return Object.entries(overlay)
      .filter(([key]) => !NON_FIELD_KEYS.has(key))
      .flatMap(([key, leaf]) => {
        const field = baseFields[key];
        if (!field || field.secret) return [];
        return [[key, mergeCapabilityLeaf(field, leaf)] as [string, CatalogField]];
      });
  }

  return Object.entries(baseFields)
    .filter(([key]) => !NON_FIELD_KEYS.has(key))
    .filter(([, field]) => !field.secret)
    .map(([key, field]) => [key, field] as [string, CatalogField]);
}

/** One named field for a (model, language) pair (e.g. "voice", "speed"). */
export function resolvedField(
  settings: ProviderSettingsCatalog | null | undefined,
  modelId: string,
  languageId: string | undefined,
  name: string,
): CatalogField | undefined {
  return resolvedModelFields(settings, modelId, languageId).find(([key]) => key === name)?.[1];
}

/**
 * Map a VoicEra canonical language id to the vendor wire code for a model.
 * Prefers `fields.language.language_codes[model]`, then
 * `capabilities[model].languages`, then the canonical id unchanged.
 */
export function vendorLanguageCode(
  settings: ProviderSettingsCatalog | null | undefined,
  modelId: string,
  canonicalId: string,
): string {
  const fromField = settings?.fields?.language?.language_codes?.[modelId]?.[canonicalId];
  if (fromField) return fromField;
  const fromCaps = settings?.capabilities?.[modelId]?.languages?.[canonicalId];
  if (fromCaps) return fromCaps;
  return canonicalId;
}

/**
 * Reverse of `vendorLanguageCode` — vendor wire code → canonical id.
 * Useful when reading older agents that stored a vendor spelling in
 * `stt_config.language` / `tts_config.language`.
 */
export function canonicalLanguageId(
  settings: ProviderSettingsCatalog | null | undefined,
  modelId: string,
  vendorCode: string,
): string {
  const fromField = settings?.fields?.language?.language_codes?.[modelId];
  if (fromField) {
    for (const [canonical, vendor] of Object.entries(fromField)) {
      if (vendor === vendorCode) return canonical;
    }
  }
  const fromCaps = settings?.capabilities?.[modelId]?.languages;
  if (fromCaps) {
    for (const [canonical, vendor] of Object.entries(fromCaps)) {
      if (vendor === vendorCode) return canonical;
    }
  }
  return vendorCode;
}

/** Build a non-secret model config blob for one model + language of a
 * provider settings catalog + user overrides (e.g. `{ voice: "…" }`).
 *
 * `overrides.language` must be a **canonical** id (for capability/voice
 * resolution). The written `language` field is the **vendor** wire code. */
export function modelConfigFromSettings(
  catalog: ProviderSettingsCatalog,
  modelId: string,
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  const canonicalLanguage =
    (typeof overrides.language === "string" && overrides.language) ||
    (catalog.fields?.language?.default !== undefined ? String(catalog.fields.language.default) : undefined);

  const out: Record<string, unknown> = { provider: catalog.provider, model: modelId };
  if (canonicalLanguage) {
    out.language = vendorLanguageCode(catalog, modelId, canonicalLanguage);
  }

  for (const [key, field] of resolvedModelFields(catalog, modelId, canonicalLanguage)) {
    if (key in overrides && overrides[key] !== undefined && overrides[key] !== "") {
      out[key] = overrides[key];
      continue;
    }
    if (field.default !== undefined && field.default !== null) {
      out[key] = field.default;
      continue;
    }
    const examples = field.examples;
    if (Array.isArray(examples) && examples.length > 0) {
      out[key] = examples[0];
    }
  }

  return out;
}

/** Every canonical language id this provider's models support — straight off
 * `fields.language.examples` (already the union across all listed models,
 * narrowed server-side when a `languages` filter was applied to the request). */
export function providerLanguageIds(settings: ProviderSettingsCatalog | null | undefined): string[] {
  const examples = settings?.fields?.language?.examples;
  return Array.isArray(examples) ? examples.map((id) => String(id)) : [];
}

export function fieldDefault(field: CatalogField): unknown {
  if (field.default !== undefined && field.default !== null) return field.default;
  if (Array.isArray(field.examples) && field.examples.length > 0) return field.examples[0];
  return "";
}

export function selectOptionsFromField(field: CatalogField): { value: string; label: string }[] {
  if (Array.isArray(field.examples) && field.examples.length > 0) {
    return field.examples.map((ex) => ({
      value: String(ex),
      label: String(ex),
    }));
  }
  return [];
}

export function secretFieldNames(catalog: {
  fields?: Record<string, CatalogField>;
  secrets?: string[];
}): string[] {
  const fromSecrets = catalog.secrets ?? [];
  if (fromSecrets.length) return fromSecrets;
  return Object.entries(catalog.fields ?? {})
    .filter(([, f]) => f.secret)
    .map(([name]) => name);
}

/** Canonical kind order for Integrations sections (API may add telephony, etc.). */
export const AUTH_KIND_ORDER = ["stt", "tts", "llm", "telephony"] as const;

export interface KindProviderGroup {
  kind: string;
  providers: { providerId: string; catalog: import("@/lib/catalog-types").AuthProviderCatalog }[];
}

/** Group catalog providers by kind; multi-kind providers appear in each relevant section. */
export function groupProvidersByKind(
  catalog: import("@/lib/catalog-types").AuthCatalog,
): KindProviderGroup[] {
  const buckets = new Map<string, KindProviderGroup["providers"]>();

  for (const [providerId, entry] of Object.entries(catalog)) {
    const kinds = entry.kinds?.length ? entry.kinds : ["other"];
    for (const kind of kinds) {
      const list = buckets.get(kind) ?? [];
      list.push({ providerId, catalog: entry });
      buckets.set(kind, list);
    }
  }

  for (const list of buckets.values()) {
    list.sort((a, b) => {
      const nameA = a.catalog.name ?? a.providerId;
      const nameB = b.catalog.name ?? b.providerId;
      return nameA.localeCompare(nameB);
    });
  }

  const orderedKinds = [
    ...AUTH_KIND_ORDER.filter((k) => buckets.has(k)),
    ...[...buckets.keys()]
      .filter((k) => !AUTH_KIND_ORDER.includes(k as (typeof AUTH_KIND_ORDER)[number]))
      .sort(),
  ];

  return orderedKinds.map((kind) => ({
    kind,
    providers: buckets.get(kind) ?? [],
  }));
}

export function humanizeFieldKey(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/\bapi\b/i, "API")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Human-readable provider deployment type (cloud / adapter / local). */
export function formatProviderTypeLabel(providerType?: string | null): string | null {
  if (!providerType) return null;
  return providerType.charAt(0).toUpperCase() + providerType.slice(1);
}

export function providerLabelWithType(name: string, providerType?: string | null): string {
  if (!providerType) return name;
  return `${name} (${providerType.toLowerCase()})`;
}
