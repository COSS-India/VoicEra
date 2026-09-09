/** Field metadata from GET /auth/catalog or GET /configuration/.../setting/... */

export interface CatalogField {
  type?: string;
  description?: string;
  default?: unknown;
  examples?: unknown[];
  secret?: boolean;
  input_mode?: string;
  minimum?: number;
  maximum?: number;
  /** Present when this field's value came from `capabilities` — the explicit
   * control to render (dropdown/slider/input/both), taking precedence over
   * the `input_mode` heuristic below when set. */
  input_type?: "dropdown" | "slider" | "input" | "both";
  /** Only meaningful when `input_type === "both"` — whether the free-text
   * entry is actually offered alongside the dropdown. */
  allow_custom_input?: boolean;
  /** On `fields.language` only: model id → { canonical id → vendor wire code }. */
  language_codes?: Record<string, Record<string, string>>;
}

export interface AuthProviderCatalog {
  provider?: string;
  name?: string;
  provider_type?: string;
  kinds?: string[];
  fields: Record<string, CatalogField>;
  secrets?: string[];
  required?: string[];
}

export type AuthCatalog = Record<string, AuthProviderCatalog>;

export interface ProviderSummary {
  provider: string;
  name: string;
  provider_type?: string;
  /** Whether this org can use the provider (credentials / local readiness). */
  authenticated?: boolean;
}

export type ProviderList = Record<string, ProviderSummary>;

/** One (model, language)-scoped setting override — narrower than `CatalogField`
 * (no `type`); `resolvedFields` merges this over the matching flat `fields`
 * entry to get the effective field for that model+language. */
export interface CapabilitySettingLeaf {
  default?: unknown;
  options?: unknown[];
  minimum?: number;
  maximum?: number;
  input_type?: "dropdown" | "slider" | "input" | "both";
  allow_custom_input?: boolean;
  description?: string;
}

/** One model's declared language support + per-language setting overrides. */
export interface ModelCapability {
  /** canonical language id -> vendor-specific language code */
  languages: Record<string, string>;
  /** canonical language id -> { setting_name -> override } */
  settings: Record<string, Record<string, CapabilitySettingLeaf>>;
}

/** GET /configuration/{kind}/setting/{provider} — a flat `fields` catalog
 * (model/language pickers + every provider knob, language-agnostic defaults)
 * plus an optional `capabilities` map for providers whose knobs vary by
 * (model, language) — e.g. TTS voice defaults, STT model language support.
 * LLM providers typically have no `capabilities` at all (language-agnostic). */
export interface ProviderSettingsCatalog {
  provider: string;
  name: string;
  provider_type?: string;
  description?: string;
  fields: Record<string, CatalogField>;
  capabilities?: Record<string, ModelCapability>;
  /** Whether this org has stored credentials for this provider. */
  authenticated?: boolean;
}

export type LanguagesMap = Record<string, string>;
