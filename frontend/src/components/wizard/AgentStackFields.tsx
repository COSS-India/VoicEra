"use client";

import { useMemo, type ReactNode } from "react";
import { motion, type Variants } from "framer-motion";
import { Brain, Mic, Volume2 } from "lucide-react";
import { Input, Select, Textarea } from "@/components/ui/Field";
import { SearchSelect } from "@/components/ui/SearchSelect";
import { InfoTip } from "@/components/ui/Tooltip";
import { LanguageSearchSelect } from "@/components/wizard/LanguageSearchSelect";
import type { CatalogField, LanguagesMap, ProviderList, ProviderSettingsCatalog } from "@/lib/catalog-types";
import { humanizeFieldKey, resolvedModelFields } from "@/lib/catalog-utils";
import type { WizardCatalogs } from "@/lib/use-wizard-catalogs";
import {
  languageLabel,
  modelOptionsFromSettings,
  searchableProviderOptions,
  voiceFieldFromSettings,
  voiceFieldIsFreeText,
  voiceOptionsFromSettings,
} from "@/lib/use-wizard-catalogs";

/** The subset of agent fields this shares between the creation wizard and the agent edit page. */
export interface StackFieldsValue {
  langs: string[];
  sttProvider: string;
  sttModel: string;
  /** Values for the selected STT model's own extra fields (base_url, …). */
  sttExtra: Record<string, unknown>;
  ttsProvider: string;
  ttsModel: string;
  /** Values for the selected TTS model's own extra fields (speed, volume, …), excluding voice. */
  ttsExtra: Record<string, unknown>;
  llmProvider: string;
  llmModel: string;
  /** Values for the selected LLM model's own extra fields (temperature, max_tokens, base_url, …). */
  llmExtra: Record<string, unknown>;
  voice: string;
}

/** Same searchable, fixed-width dropdown used for provider pickers — plain
 * `<Select>` let long option text (e.g. a voice's full description) overflow
 * its panel; this one truncates the trigger and every row, and its menu is
 * pinned to the trigger's own width, so it never runs past the container. */
function DropdownControl({
  field,
  value,
  onChange,
}: {
  field: CatalogField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const options = (field.examples ?? []).map((ex) => ({ value: String(ex), label: String(ex) }));
  const current =
    value !== undefined && value !== null
      ? String(value)
      : field.default !== undefined && field.default !== null
        ? String(field.default)
        : String(field.examples![0]);
  return <SearchSelect options={options} value={current} onChange={onChange} placeholder="Select…" />;
}

function SliderControl({
  field,
  value,
  onChange,
}: {
  field: CatalogField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const min = field.minimum ?? 0;
  const fallbackMax = typeof field.default === "number" ? Math.max(field.default * 4, field.default + 10, 100) : 100;
  const max = field.maximum ?? fallbackMax;
  const step = field.type?.startsWith("integer") ? 1 : Math.max((max - min) / 100, 0.01);
  const numericValue = typeof value === "number" ? value : typeof field.default === "number" ? field.default : min;
  return (
    <span className="flex flex-col gap-1.5">
      <span className="self-end font-mono text-[11px] font-normal text-v-muted">{numericValue}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={numericValue}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-v-line accent-v-accent"
      />
    </span>
  );
}

/** The custom-value half of a "both" (dropdown + custom) field — a multi-line
 * box directly editable in place: picking a dropdown option fills it, and you
 * can type into the same box to override with your own value. Textarea (not
 * a single-line input) since these are often long, e.g. a voice description. */
function TextareaControl({
  field,
  value,
  onChange,
}: {
  field: CatalogField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  return (
    <Textarea
      value={value !== undefined && value !== null ? String(value) : ""}
      onChange={(e) => onChange(e.target.value)}
      rows={4}
      placeholder={field.default !== undefined && field.default !== null ? String(field.default) : "Type a custom value…"}
    />
  );
}

function TextControl({
  field,
  value,
  onChange,
}: {
  field: CatalogField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  return (
    <Input
      value={value !== undefined && value !== null ? String(value) : ""}
      onChange={(e) => onChange(e.target.value)}
      placeholder={field.default !== undefined && field.default !== null ? String(field.default) : ""}
    />
  );
}

/** One "other key" of a chosen model. When the field came from `capabilities`
 * it carries an explicit `input_type` — honored exactly: "dropdown" -> select
 * only, "slider" -> range only, "input" -> free text only, "both" -> select
 * *and* free text together, but only when `allow_custom_input` says so.
 * Flat-only fields (no capabilities entry, e.g. an LLM's temperature) have no
 * `input_type` — those fall back to the older input_mode/type heuristic. */
function DynamicModelField({
  fieldKey,
  field,
  value,
  onChange,
}: {
  fieldKey: string;
  field: CatalogField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const label = humanizeFieldKey(fieldKey);
  const hasOptions = Array.isArray(field.examples) && field.examples.length > 0;
  const isNumeric = field.type?.startsWith("number") || field.type?.startsWith("integer");

  let showDropdown: boolean;
  let showCustom: boolean;
  let customIsSlider: boolean;

  if (field.input_type) {
    showDropdown = hasOptions && (field.input_type === "dropdown" || field.input_type === "both");
    showCustom =
      !hasOptions ||
      field.input_type === "input" ||
      field.input_type === "slider" ||
      (field.input_type === "both" && field.allow_custom_input === true);
    customIsSlider = field.input_type === "slider";
  } else {
    const isOptions = field.input_mode === "options" && hasOptions;
    showDropdown = isOptions;
    showCustom = !isOptions;
    customIsSlider = !isOptions && Boolean(isNumeric);
  }

  return (
    <div className="flex flex-col gap-1.5 text-[13px] font-medium">
      <span className="flex items-center gap-1.5">
        {label}
        {field.description ? <InfoTip text={field.description} /> : null}
      </span>
      {showDropdown ? <DropdownControl field={field} value={value} onChange={onChange} /> : null}
      {showCustom ? (
        showDropdown ? (
          <TextareaControl field={field} value={value} onChange={onChange} />
        ) : customIsSlider ? (
          <SliderControl field={field} value={value} onChange={onChange} />
        ) : (
          <TextControl field={field} value={value} onChange={onChange} />
        )
      ) : null}
    </div>
  );
}

const sectionVariants: Variants = {
  hidden: { opacity: 0, y: 14 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.07, duration: 0.35, ease: [0.4, 0, 0.2, 1] as const },
  }),
};

export type StackFieldsSection = "languages" | "llm" | "stt" | "tts";

const ALL_SECTIONS: StackFieldsSection[] = ["languages", "llm", "stt", "tts"];

interface AgentStackFieldsProps {
  value: StackFieldsValue;
  onChange: <K extends keyof StackFieldsValue>(key: K, value: StackFieldsValue[K]) => void;
  catalogs: WizardCatalogs;
  /** Which subsections to render — omit to render all (the creation wizard's default). */
  sections?: StackFieldsSection[];
  /** Extra card rendered after the last section (e.g. the wizard's Delivery section). */
  trailing?: ReactNode;
}

type SectionProps = Pick<AgentStackFieldsProps, "value" | "onChange" | "catalogs">;

/** "Hindi (primary) · English" — the first selected language opens the call. */
function languageSummary(langs: string[], languages: LanguagesMap): string {
  if (langs.length === 0) return "No languages selected";
  return langs.map((id, i) => `${languageLabel(languages, id)}${i === 0 ? " (primary)" : ""}`).join(" · ");
}

/** Only offer languages the org's configured STT/TTS providers actually support, but
 * always keep already-selected languages resolvable to a label even if config changed since. */
function mergeSelectableLanguages(
  available: LanguagesMap,
  all: LanguagesMap,
  selected: string[],
): LanguagesMap {
  const merged = { ...available };
  for (const id of selected) {
    if (!merged[id] && all[id]) merged[id] = all[id];
  }
  return merged;
}

/** Languages card: the multi-select plus a "primary first" summary. */
function LanguagesSection({ value, onChange, catalogs }: SectionProps) {
  const selectableLanguages = useMemo(
    () => mergeSelectableLanguages(catalogs.availableLanguages, catalogs.languages, value.langs),
    [catalogs.availableLanguages, catalogs.languages, value.langs],
  );
  const loading = catalogs.loading || catalogs.languagesLoading;
  const noneSupported = !loading && Object.keys(selectableLanguages).length === 0;

  return (
    <motion.section
      custom={0}
      initial="hidden"
      animate="visible"
      variants={sectionVariants}
      className="flex flex-col gap-3 rounded-v-md border border-v-line bg-white p-5"
    >
      <span className="flex items-center gap-2 text-[14.5px] font-semibold">
        Languages
        <InfoTip text="The first language opens the call. Additional languages are secondary." />
      </span>
      <LanguageSearchSelect
        languages={selectableLanguages}
        selected={value.langs}
        onChange={(ids) => onChange("langs", ids)}
        disabled={loading}
      />
      {noneSupported ? (
        <p className="text-xs font-light text-v-muted">
          No configured STT/TTS provider declares language support — add one under Integrations first.
        </p>
      ) : null}
      {value.langs.length > 0 ? (
        <p className="text-xs font-light text-v-muted">{languageSummary(value.langs, catalogs.languages)}</p>
      ) : null}
    </motion.section>
  );
}

/** Provider search + model dropdown shared by the STT and TTS cards. */
function ProviderModelPickers({
  kind,
  providers,
  settings,
  provider,
  model,
  onProvider,
  onModel,
}: {
  kind: "STT" | "TTS";
  providers: ProviderList;
  settings: ProviderSettingsCatalog | null;
  provider: string;
  model: string;
  onProvider: (provider: string) => void;
  onModel: (model: string) => void;
}) {
  const options = searchableProviderOptions(providers);
  const hasConfigured = options.some((o) => !o.disabled);
  const models = modelOptionsFromSettings(settings);
  return (
    <>
      <label className="flex flex-col gap-1.5 text-[13px] font-medium">
        Provider
        <SearchSelect
          options={options}
          value={provider}
          onChange={onProvider}
          placeholder={`Search ${kind} providers…`}
          disabled={options.length === 0}
        />
        {!hasConfigured ? (
          <span className="text-xs font-light text-v-muted">
            No {kind} provider connected yet — add one under Integrations first.
          </span>
        ) : settings?.description ? (
          <span className="text-xs font-light text-v-muted">{settings.description}</span>
        ) : null}
      </label>

      {models.length > 0 ? (
        <label className="flex flex-col gap-1.5 text-[13px] font-medium">
          Model
          <Select value={model} onChange={(e) => onModel(e.target.value)} disabled={!provider}>
            <option value="">Select model…</option>
            {models.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </Select>
        </label>
      ) : null}
    </>
  );
}

/** Card frame shared by the STT and TTS sections. */
function StackCard({
  tour,
  index,
  icon,
  title,
  tip,
  children,
}: {
  tour: string;
  index: number;
  icon: ReactNode;
  title: string;
  tip: string;
  children: ReactNode;
}) {
  return (
    <motion.section
      data-tour={tour}
      custom={index}
      initial="hidden"
      animate="visible"
      variants={sectionVariants}
      className="flex flex-col gap-4 rounded-v-md border border-v-line bg-white p-5"
    >
      <span className="flex items-center gap-2 text-[14.5px] font-semibold">
        {icon}
        {title}
        <InfoTip text={tip} />
      </span>
      {children}
    </motion.section>
  );
}

/** The selected model's own extra fields (speed, base_url, …) as generic controls. */
function ModelExtraFields({
  fields,
  values,
  onChange,
}: {
  fields: [string, CatalogField][];
  values: Record<string, unknown>;
  onChange: (values: Record<string, unknown>) => void;
}) {
  return fields.map(([key, field]) => (
    <DynamicModelField
      key={key}
      fieldKey={key}
      field={field}
      value={values[key]}
      onChange={(v) => onChange({ ...values, [key]: v })}
    />
  ));
}

/** Transcriber (STT) card: provider, model, then the model's own extra fields. */
function SttSection({ value, onChange, catalogs }: SectionProps) {
  return (
    <StackCard
      tour="stt-section"
      index={1}
      icon={<Mic className="size-4 text-v-muted" strokeWidth={1.9} />}
      title="Transcriber (STT)"
      tip="Converts caller speech to text."
    >
      <ProviderModelPickers
        kind="STT"
        providers={catalogs.sttProviders}
        settings={catalogs.sttSettings}
        provider={value.sttProvider}
        model={value.sttModel}
        onProvider={(v) => onChange("sttProvider", v)}
        onModel={(v) => onChange("sttModel", v)}
      />
      <ModelExtraFields
        fields={resolvedModelFields(catalogs.sttSettings, value.sttModel, value.langs[0])}
        values={value.sttExtra}
        onChange={(v) => onChange("sttExtra", v)}
      />
    </StackCard>
  );
}

/** Voice picker for the selected TTS (model, primary language): a dropdown when
 * the catalog lists voices, a free-text id (e.g. Cartesia's UUID) when it
 * doesn't, nothing when the provider has no voice field. */
function TtsVoiceField({ value, onChange, catalogs }: SectionProps) {
  const primaryLang = value.langs[0];
  const voices = voiceOptionsFromSettings(catalogs.ttsSettings, value.ttsModel, primaryLang);
  const voiceField = voiceFieldFromSettings(catalogs.ttsSettings, value.ttsModel, primaryLang);
  if (voices.length > 0) {
    return (
      <label className="flex flex-col gap-1.5 text-[13px] font-medium">
        Voice
        <Select value={value.voice} onChange={(e) => onChange("voice", e.target.value)}>
          <option value="">Select voice…</option>
          {voices.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name}
            </option>
          ))}
        </Select>
      </label>
    );
  }
  if (!voiceFieldIsFreeText(catalogs.ttsSettings, value.ttsModel, primaryLang)) return null;
  return (
    <label className="flex flex-col gap-1.5 text-[13px] font-medium">
      Voice ID
      <Input
        value={value.voice}
        onChange={(e) => onChange("voice", e.target.value)}
        placeholder={voiceField?.default ? String(voiceField.default) : "Voice id…"}
      />
      {voiceField?.description ? (
        <span className="text-xs font-light text-v-muted">{voiceField.description}</span>
      ) : null}
    </label>
  );
}

/** The Voice (TTS) card: provider, model, voice, then the model's own
 * extra fields ("voice" excluded — TtsVoiceField renders it). */
function TtsSection({ value, onChange, catalogs }: SectionProps) {
  const ttsModelFields = resolvedModelFields(catalogs.ttsSettings, value.ttsModel, value.langs[0]).filter(
    ([key]) => key !== "voice",
  );
  return (
    <StackCard
      tour="tts-section"
      index={3}
      icon={<Volume2 className="size-4 text-v-muted" strokeWidth={1.9} />}
      title="Voice (TTS)"
      tip="Speaks the agent's replies."
    >
      <ProviderModelPickers
        kind="TTS"
        providers={catalogs.ttsProviders}
        settings={catalogs.ttsSettings}
        provider={value.ttsProvider}
        model={value.ttsModel}
        onProvider={(v) => onChange("ttsProvider", v)}
        onModel={(v) => onChange("ttsModel", v)}
      />
      <TtsVoiceField value={value} onChange={onChange} catalogs={catalogs} />
      <ModelExtraFields fields={ttsModelFields} values={value.ttsExtra} onChange={(v) => onChange("ttsExtra", v)} />
    </StackCard>
  );
}

/**
 * Language + STT/TTS/LLM/voice fields, shared by the agent-creation wizard's Stack step
 * and the agent edit page so both stay in sync with a single implementation.
 */
export function AgentStackFields({
  value,
  onChange,
  catalogs,
  sections = ALL_SECTIONS,
  trailing,
}: AgentStackFieldsProps) {
  // catalogs.sttProviders/ttsProviders are re-fetched from /configuration/{stt,tts}
  // every time the selected language(s) change (see useWizardCatalogs). Every
  // provider is listed; only `authenticated: true` entries are selectable.
  // LLM has no language dependency. STT/TTS/Languages cards are their own components.
  const llmOpts = searchableProviderOptions(catalogs.llmProviders);
  const llmHasConfigured = llmOpts.some((o) => !o.disabled);
  const llmModels = modelOptionsFromSettings(catalogs.llmSettings);
  // Provider settings can vary by (model, language) via `capabilities` — the
  // primary language is what everything below resolves against.
  const primaryLang = value.langs[0];
  // The LLM model's own extra fields — rendered as a second tier of controls
  // once a model is picked.
  const llmModelFields = resolvedModelFields(catalogs.llmSettings, value.llmModel, primaryLang);

  const showLanguages = sections.includes("languages");
  const showLlm = sections.includes("llm");
  const showStt = sections.includes("stt");
  const showTts = sections.includes("tts");

  return (
    <div className="flex flex-col gap-5">
      {showLanguages ? <LanguagesSection value={value} onChange={onChange} catalogs={catalogs} /> : null}

      {showStt ? <SttSection value={value} onChange={onChange} catalogs={catalogs} /> : null}

      {showLlm ? (
        <motion.section
          data-tour="llm-section"
          custom={2}
          initial="hidden"
          animate="visible"
          variants={sectionVariants}
          className="flex flex-col gap-4 rounded-v-md border border-v-line bg-white p-5"
        >
          <span className="flex items-center gap-2 text-[14.5px] font-semibold">
            <Brain className="size-4 text-v-muted" strokeWidth={1.9} />
            Language model (LLM)
            <InfoTip text="Powers reasoning and dialogue." />
          </span>
          <label className="flex flex-col gap-1.5 text-[13px] font-medium">
            Provider
            <SearchSelect
              options={llmOpts}
              value={value.llmProvider}
              onChange={(v) => onChange("llmProvider", v)}
              placeholder="Search LLM providers…"
              disabled={llmOpts.length === 0}
            />
            {!llmHasConfigured ? (
              <span className="text-xs font-light text-v-muted">
                No LLM provider connected yet — add one under Integrations first.
              </span>
            ) : null}
          </label>

          <label className="flex flex-col gap-1.5 text-[13px] font-medium">
            Model
            <Select
              value={value.llmModel}
              onChange={(e) => onChange("llmModel", e.target.value)}
              disabled={!value.llmProvider}
            >
              <option value="">Select model…</option>
              {llmModels.map((m) => (
                <option key={m.value} value={m.value}>
                  {m.label}
                </option>
              ))}
            </Select>
          </label>

          {llmModelFields.map(([key, field]) => (
            <DynamicModelField
              key={key}
              fieldKey={key}
              field={field}
              value={value.llmExtra[key]}
              onChange={(v) => onChange("llmExtra", { ...value.llmExtra, [key]: v })}
            />
          ))}
        </motion.section>
      ) : null}

      {showTts ? <TtsSection value={value} onChange={onChange} catalogs={catalogs} /> : null}

      {trailing}
    </div>
  );
}
