"use client";

import { Brain, Mic, Volume2 } from "lucide-react";
import { Input, Select, Textarea } from "@/components/ui/Field";
import { SearchSelect } from "@/components/ui/SearchSelect";
import { InfoTip } from "@/components/ui/Tooltip";
import type { CatalogField } from "@/lib/catalog-types";
import { humanizeFieldKey, resolvedModelFields } from "@/lib/catalog-utils";
import type { LanguageStack } from "@/lib/language-stacks";
import type { WizardCatalogs } from "@/lib/use-wizard-catalogs";
import {
  modelOptionsFromSettings,
  searchableProviderOptions,
  voiceFieldFromSettings,
  voiceFieldIsFreeText,
  voiceOptionsFromSettings,
} from "@/lib/use-wizard-catalogs";

export type StackEditorSection = "stt" | "llm" | "tts";

function DropdownControl({
  field,
  value,
  onChange,
}: {
  field: CatalogField;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const options = (field.examples ?? []).map((ex) => {
    const value = String(ex);
    return { value, label: field.option_labels?.[value] ?? value };
  });
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
  // An optional knob with no default is *unset*, not zero — and not the minimum,
  // which is what the thumb has to rest on. Saying so keeps the form from
  // claiming a value nobody chose (a penalty reading -2 is not a penalty of -2).
  const isSet = typeof value === "number" || typeof field.default === "number";
  return (
    <span className="flex flex-col gap-1.5">
      <span className="flex items-center justify-end gap-2 font-mono text-[11px] font-normal text-v-muted">
        {isSet ? numericValue : "Not set"}
        {typeof value === "number" ? (
          <button
            type="button"
            onClick={() => onChange("")}
            className="cursor-pointer font-sans underline underline-offset-2 hover:text-v-fg"
          >
            Clear
          </button>
        ) : null}
      </span>
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

/** A numeric knob without a bounded range (max_tokens, seed). A slider needs
 * two ends; inventing one caps the field at an arbitrary ceiling — the old
 * fallback silently made "Max Tokens" unsettable above 100. Blank submits
 * nothing, so the endpoint's own default applies. */
function NumberControl({
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
      type="number"
      min={field.minimum}
      max={field.maximum}
      value={value === undefined || value === null ? "" : String(value)}
      onChange={(e) => onChange(e.target.value === "" ? "" : Number(e.target.value))}
      placeholder={
        field.default !== undefined && field.default !== null
          ? String(field.default)
          : "Endpoint default"
      }
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
    // Only a field bounded at both ends gets a slider.
    customIsSlider =
      !isOptions && Boolean(isNumeric) && field.minimum != null && field.maximum != null;
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
        ) : isNumeric ? (
          <NumberControl field={field} value={value} onChange={onChange} />
        ) : (
          <TextControl field={field} value={value} onChange={onChange} />
        )
      ) : null}
    </div>
  );
}

interface LanguageStackEditorProps {
  lang: string;
  stack: LanguageStack;
  catalogs: WizardCatalogs;
  onStackChange: (patch: Partial<LanguageStack>) => void;
  sections?: StackEditorSection[];
  catalogsLoading?: boolean;
}

/** Inline STT / LLM / TTS controls for one language stack. */
export function LanguageStackEditor({
  lang,
  stack,
  catalogs,
  onStackChange,
  sections = ["stt", "llm", "tts"],
  catalogsLoading = false,
}: LanguageStackEditorProps) {
  const sttOpts = searchableProviderOptions(catalogs.sttProviders);
  const ttsOpts = searchableProviderOptions(catalogs.ttsProviders);
  const llmOpts = searchableProviderOptions(catalogs.llmProviders);
  const sttHasConfigured = sttOpts.some((o) => !o.disabled);
  const ttsHasConfigured = ttsOpts.some((o) => !o.disabled);
  const llmHasConfigured = llmOpts.some((o) => !o.disabled);
  const llmModels = modelOptionsFromSettings(catalogs.llmSettings);
  const sttModels = modelOptionsFromSettings(catalogs.sttSettings);
  const ttsModels = modelOptionsFromSettings(catalogs.ttsSettings);

  const voices = voiceOptionsFromSettings(catalogs.ttsSettings, stack.ttsModel, lang);
  const voiceField = voiceFieldFromSettings(catalogs.ttsSettings, stack.ttsModel, lang);
  const voiceIsFreeText = voiceFieldIsFreeText(catalogs.ttsSettings, stack.ttsModel, lang);

  const sttModelFields = resolvedModelFields(catalogs.sttSettings, stack.sttModel, lang);
  const ttsModelFields = resolvedModelFields(catalogs.ttsSettings, stack.ttsModel, lang).filter(
    ([key]) => key !== "voice",
  );
  // `connection_id` gets its own endpoint picker below, so it is kept out of
  // the generic field renderer that handles temperature, top_p, and the rest.
  const llmModelFields = resolvedModelFields(catalogs.llmSettings, stack.llmModel, lang).filter(
    ([key]) => key !== "connection_id",
  );
  const llmIsConnectionBased = catalogs.llmSettings?.connection_based === true;
  const selectedConnectionId = String(stack.llmExtra.connection_id ?? "");
  const selectedConnection = catalogs.llmConnections.find((c) => c.id === selectedConnectionId);
  // A connection-based provider publishes no vendor model list; the ids come
  // from whatever the chosen endpoint reported when it was last tested.
  const llmModelChoices = llmIsConnectionBased
    ? (() => {
        const ids = selectedConnection?.models ?? [];
        // An endpoint's model list can change under a saved agent; keep the
        // stored id selectable so editing anything else does not silently
        // blank it.
        const withCurrent =
          stack.llmModel && !ids.includes(stack.llmModel) ? [stack.llmModel, ...ids] : ids;
        return withCurrent.map((id) => ({ value: id, label: id }));
      })()
    : llmModels;

  if (catalogsLoading) {
    return <p className="px-1 py-2 text-xs font-light text-v-muted">Loading provider settings…</p>;
  }

  const sectionBox = "flex flex-col gap-4 rounded-v-md border border-v-line bg-white p-5";

  return (
    <div className="flex flex-col gap-4">
      {sections.includes("stt") ? (
        <div data-tour="stt-section" className={sectionBox}>
          <span className="flex items-center gap-2 text-[13.5px] font-semibold">
            <Mic className="size-4 text-v-muted" strokeWidth={1.9} />
            Transcriber (STT)
            <InfoTip text="Converts caller speech to text." />
          </span>
          <label className="flex flex-col gap-1.5 text-[13px] font-medium">
            Provider
            <SearchSelect
              options={sttOpts}
              value={stack.sttProvider}
              onChange={(v) => onStackChange({ sttProvider: v, sttModel: "" })}
              placeholder="Search STT providers…"
              disabled={sttOpts.length === 0}
            />
            {!sttHasConfigured ? (
              <span className="text-xs font-light text-v-muted">
                No STT provider connected yet — add one under Integrations first.
              </span>
            ) : catalogs.sttSettings?.description ? (
              <span className="text-xs font-light text-v-muted">{catalogs.sttSettings.description}</span>
            ) : null}
          </label>
          {sttModels.length > 0 ? (
            <label className="flex flex-col gap-1.5 text-[13px] font-medium">
              Model
              <Select
                value={stack.sttModel}
                onChange={(e) => onStackChange({ sttModel: e.target.value })}
                disabled={!stack.sttProvider}
              >
                <option value="">Select model…</option>
                {sttModels.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </Select>
            </label>
          ) : null}
          {sttModelFields.map(([key, field]) => (
            <DynamicModelField
              key={key}
              fieldKey={key}
              field={field}
              value={stack.sttExtra[key]}
              onChange={(v) => onStackChange({ sttExtra: { ...stack.sttExtra, [key]: v } })}
            />
          ))}
        </div>
      ) : null}

      {sections.includes("llm") ? (
        <div data-tour="llm-section" className={sectionBox}>
          <span className="flex items-center gap-2 text-[13.5px] font-semibold">
            <Brain className="size-4 text-v-muted" strokeWidth={1.9} />
            Language model (LLM)
            <InfoTip text="Powers reasoning and dialogue." />
          </span>
          <label className="flex flex-col gap-1.5 text-[13px] font-medium">
            Provider
            <SearchSelect
              options={llmOpts}
              value={stack.llmProvider}
              onChange={(v) => onStackChange({ llmProvider: v, llmModel: "" })}
              placeholder="Search LLM providers…"
              disabled={llmOpts.length === 0}
            />
            {!llmHasConfigured ? (
              <span className="text-xs font-light text-v-muted">
                No LLM provider connected yet — add one under Integrations first.
              </span>
            ) : null}
          </label>
          {llmIsConnectionBased ? (
            <label className="flex flex-col gap-1.5 text-[13px] font-medium">
              Endpoint
              <SearchSelect
                options={catalogs.llmConnections.map((c) => ({ value: c.id, label: c.name }))}
                value={selectedConnectionId}
                onChange={(v) => {
                  const next = catalogs.llmConnections.find((c) => c.id === v);
                  onStackChange({
                    llmExtra: { ...stack.llmExtra, connection_id: v },
                    // Models are per endpoint, so a model picked for the previous
                    // one would be sent to a host that never served it.
                    llmModel: next?.default_model ?? "",
                  });
                }}
                placeholder="Select endpoint…"
                disabled={catalogs.llmConnections.length === 0}
              />
              <span className="text-xs font-light text-v-muted">
                {catalogs.llmConnections.length === 0
                  ? "No OpenAI-compatible endpoint yet — add one under Integrations first."
                  : (selectedConnection?.base_url ?? "Each endpoint carries its own URL and key.")}
              </span>
            </label>
          ) : null}
          <label className="flex flex-col gap-1.5 text-[13px] font-medium">
            Model
            {llmModelChoices.length > 0 ? (
              <Select
                value={stack.llmModel}
                onChange={(e) => onStackChange({ llmModel: e.target.value })}
                disabled={!stack.llmProvider}
              >
                <option value="">Select model…</option>
                {llmModelChoices.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </Select>
            ) : (
              // A provider with no fixed vendor catalog publishes no model
              // examples, so the id has to be typed. STT and TTS pickers can
              // adopt this the day a provider needs it.
              <Input
                value={stack.llmModel}
                onChange={(e) => onStackChange({ llmModel: e.target.value })}
                disabled={!stack.llmProvider || (llmIsConnectionBased && !selectedConnectionId)}
                placeholder="Model id served by the endpoint"
              />
            )}
          </label>
          {llmModelFields.map(([key, field]) => (
            <DynamicModelField
              key={key}
              fieldKey={key}
              field={field}
              value={stack.llmExtra[key]}
              onChange={(v) => onStackChange({ llmExtra: { ...stack.llmExtra, [key]: v } })}
            />
          ))}
        </div>
      ) : null}

      {sections.includes("tts") ? (
        <div data-tour="tts-section" className={sectionBox}>
          <span className="flex items-center gap-2 text-[13.5px] font-semibold">
            <Volume2 className="size-4 text-v-muted" strokeWidth={1.9} />
            Voice (TTS)
            <InfoTip text="Speaks the agent's replies." />
          </span>
          <label className="flex flex-col gap-1.5 text-[13px] font-medium">
            Provider
            <SearchSelect
              options={ttsOpts}
              value={stack.ttsProvider}
              onChange={(v) => onStackChange({ ttsProvider: v, ttsModel: "", voice: "" })}
              placeholder="Search TTS providers…"
              disabled={ttsOpts.length === 0}
            />
            {!ttsHasConfigured ? (
              <span className="text-xs font-light text-v-muted">
                No TTS provider connected yet — add one under Integrations first.
              </span>
            ) : catalogs.ttsSettings?.description ? (
              <span className="text-xs font-light text-v-muted">{catalogs.ttsSettings.description}</span>
            ) : null}
          </label>
          {ttsModels.length > 0 ? (
            <label className="flex flex-col gap-1.5 text-[13px] font-medium">
              Model
              <Select
                value={stack.ttsModel}
                onChange={(e) => onStackChange({ ttsModel: e.target.value, voice: "" })}
                disabled={!stack.ttsProvider}
              >
                <option value="">Select model…</option>
                {ttsModels.map((m) => (
                  <option key={m.value} value={m.value}>
                    {m.label}
                  </option>
                ))}
              </Select>
            </label>
          ) : null}
          {voices.length > 0 ? (
            <label className="flex flex-col gap-1.5 text-[13px] font-medium">
              Voice
              <Select value={stack.voice} onChange={(e) => onStackChange({ voice: e.target.value })}>
                <option value="">Select voice…</option>
                {voices.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name}
                  </option>
                ))}
              </Select>
            </label>
          ) : voiceIsFreeText ? (
            <label className="flex flex-col gap-1.5 text-[13px] font-medium">
              Voice ID
              <Input
                value={stack.voice}
                onChange={(e) => onStackChange({ voice: e.target.value })}
                placeholder={voiceField?.default ? String(voiceField.default) : "Voice id…"}
              />
              {voiceField?.description ? (
                <span className="text-xs font-light text-v-muted">{voiceField.description}</span>
              ) : null}
            </label>
          ) : null}
          {ttsModelFields.map(([key, field]) => (
            <DynamicModelField
              key={key}
              fieldKey={key}
              field={field}
              value={stack.ttsExtra[key]}
              onChange={(v) => onStackChange({ ttsExtra: { ...stack.ttsExtra, [key]: v } })}
            />
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function stackSummaryLine(stack: LanguageStack, catalogs: WizardCatalogs): string {
  const parts = [
    catalogs.sttProviders[stack.sttProvider]?.name ?? stack.sttProvider,
    catalogs.ttsProviders[stack.ttsProvider]?.name ?? stack.ttsProvider,
    catalogs.llmProviders[stack.llmProvider]?.name ?? stack.llmProvider,
  ].filter(Boolean);
  return parts.join(" · ");
}
