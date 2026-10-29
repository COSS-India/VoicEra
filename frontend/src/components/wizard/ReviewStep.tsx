"use client";

import { useLayoutEffect, useMemo, useRef, useState } from "react";
import { Pencil } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { useAuth } from "@/components/AuthProvider";
import { createAgent, updateAgent } from "@/lib/api-client";
import { formToAgentCreatePayload } from "@/lib/agent-mapper";
import { resolveSaveCatalogs } from "@/lib/language-stacks";
import { BrowserCallSession } from "@/components/call/BrowserCallSession";
import {
  formatServiceLine,
  LanguageStacksPanel,
  type LanguageStackSummary,
} from "@/components/dashboard/LanguageStacksPanel";
import type { AgentForm } from "@/lib/wizard-data";
import type { AgentApiResponse } from "@/lib/api-types";
import type { WizardCatalogs } from "@/lib/use-wizard-catalogs";
import { languageLabel, telephonyOptions } from "@/lib/use-wizard-catalogs";
import { AGENT_NAME_MAX_LENGTH } from "@/lib/wizard-data";

interface ReviewStepProps {
  form: AgentForm;
  catalogs: WizardCatalogs;
  onChange: <K extends keyof AgentForm>(key: K, value: AgentForm[K]) => void;
  /** "create" saves a brand-new agent; "edit" saves changes to an existing one. */
  mode?: "create" | "edit";
  /** Owned by the parent wizard (not this component) so it survives this step
   * unmounting when the user navigates elsewhere and comes back — otherwise a
   * "create"-mode draft agent would get re-created (and 409) on every revisit. */
  agentId: string | null;
  /** Called after every successful create/update, so the parent can store the id. */
  onAgentSaved: (agent: AgentApiResponse) => void;
  /** "create" mode only — moves on once the draft agent is ready. */
  onFinish?: () => void;
  /** Jump back to a given step id to fix something — powers the edit icons below. */
  onEditStep?: (stepId: string) => void;
}

type InlineReviewField = "name" | "welcome";

function SummaryRow({
  label,
  value,
  onEdit,
}: {
  label: string;
  value: string;
  onEdit?: () => void;
}) {
  return (
    <div className="flex items-center justify-between gap-2 border-b border-v-hairline py-2.5 last:border-0">
      <div className="flex min-w-0 flex-col gap-0.5">
        <span className="font-mono text-[9.5px] uppercase tracking-[.14em] text-v-muted">{label}</span>
        <span className="truncate text-[13px] text-v-fg">{value}</span>
      </div>
      {onEdit ? (
        <button
          type="button"
          aria-label={`Edit ${label.toLowerCase()}`}
          onClick={onEdit}
          className="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-v-sm border border-v-line text-v-muted transition-colors hover:bg-v-soft hover:text-v-fg"
        >
          <Pencil className="size-3.5" strokeWidth={1.8} />
        </button>
      ) : null}
    </div>
  );
}

/** Name and greeting are tweaked often on Review — pencil toggles inline edit
 * instead of leaving the step (other rows still jump back via onEditStep). */
const inlineFieldClass =
  "w-full box-border rounded-v-lg border border-v-line-strong bg-white text-v-fg text-[13px] px-3 py-2 transition-colors duration-[120ms] ease-out focus:border-v-accent focus:border-[1.5px] focus:shadow-[0_0_0_4px_rgba(31,78,232,0.10)] focus:outline-none";

function InlineSummaryRow({
  label,
  field,
  readValue,
  editValue,
  editingField,
  onStartEdit,
  onChangeValue,
  inputType = "text",
  maxLength,
}: {
  label: string;
  field: InlineReviewField;
  readValue: string;
  editValue: string;
  editingField: InlineReviewField | null;
  onStartEdit: (field: InlineReviewField) => void;
  onChangeValue: (value: string) => void;
  inputType?: "text" | "textarea";
  maxLength?: number;
}) {
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null);
  const isEditing = editingField === field;

  useLayoutEffect(() => {
    if (!isEditing) return;
    const el = inputRef.current;
    if (!el) return;
    el.focus();
    if ("setSelectionRange" in el) {
      const len = el.value.length;
      el.setSelectionRange(len, len);
    }
  }, [isEditing]);

  return (
    <div className="flex items-start justify-between gap-2 border-b border-v-hairline py-2.5 last:border-0">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <span className="font-mono text-[9.5px] uppercase tracking-[.14em] text-v-muted">{label}</span>
        {isEditing ? (
          inputType === "textarea" ? (
            <textarea
              ref={inputRef as React.RefObject<HTMLTextAreaElement>}
              value={editValue}
              rows={2}
              className={`${inlineFieldClass} resize-none`}
              onChange={(e) => onChangeValue(e.target.value)}
            />
          ) : (
            <input
              ref={inputRef as React.RefObject<HTMLInputElement>}
              type="text"
              value={editValue}
              maxLength={maxLength}
              className={inlineFieldClass}
              onChange={(e) =>
                onChangeValue(maxLength ? e.target.value.slice(0, maxLength) : e.target.value)
              }
            />
          )
        ) : (
          <span className="truncate text-[13px] text-v-fg">{readValue}</span>
        )}
      </div>
      <button
        type="button"
        aria-label={`Edit ${label.toLowerCase()}`}
        aria-pressed={isEditing}
        onClick={() => onStartEdit(field)}
        className={`flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-v-sm border border-v-line transition-colors hover:bg-v-soft hover:text-v-fg ${
          isEditing ? "bg-v-soft text-v-fg" : "text-v-muted"
        }`}
      >
        <Pencil className="size-3.5" strokeWidth={1.8} />
      </button>
    </div>
  );
}

function languageStackSummaries(
  form: AgentForm,
  catalogs: WizardCatalogs,
): LanguageStackSummary[] {
  return form.langs.map((lang) => {
    const stack = form.languageStacks[lang];
    const sttName = catalogs.sttProviders[stack?.sttProvider ?? ""]?.name ?? stack?.sttProvider ?? "—";
    const ttsName = catalogs.ttsProviders[stack?.ttsProvider ?? ""]?.name ?? stack?.ttsProvider ?? "—";
    const llmName = catalogs.llmProviders[stack?.llmProvider ?? ""]?.name ?? stack?.llmProvider ?? "—";
    return {
      langId: lang,
      label: languageLabel(catalogs.languages, lang),
      isPrimary: lang === form.primaryLang,
      stt: formatServiceLine(sttName, stack?.sttModel),
      tts: formatServiceLine(ttsName, stack?.ttsModel, stack?.voice),
      llm: formatServiceLine(llmName, stack?.llmModel),
    };
  });
}

/** Read-only recap of every choice made across the wizard — the "what has
 * been chosen" list next to the test-call box. Each row's pencil jumps back
 * to the step that owns it. */
function SelectionsSummary({
  form,
  catalogs,
  onChange,
  onEditStep,
}: {
  form: AgentForm;
  catalogs: WizardCatalogs;
  onChange: <K extends keyof AgentForm>(key: K, value: AgentForm[K]) => void;
  onEditStep?: (stepId: string) => void;
}) {
  const [editingField, setEditingField] = useState<InlineReviewField | null>(null);

  const deliveryLabel =
    telephonyOptions(catalogs.telephonyProviders).find((d) => d.value === form.delivery)?.label ??
    "WebSocket — browser test";

  const editStep = (id: string) => (onEditStep ? () => onEditStep(id) : undefined);
  const stacks = useMemo(() => languageStackSummaries(form, catalogs), [form, catalogs]);

  const startInlineEdit = (field: InlineReviewField) => {
    setEditingField(field);
  };

  return (
    <div className="flex h-max flex-col gap-3 rounded-v-md border border-v-line bg-white p-4.5">
      <span className="font-mono text-[10px] uppercase tracking-[.16em] text-v-muted">
        What you&apos;ve chosen
      </span>

      <div className="flex flex-col">
        <InlineSummaryRow
          label="Name"
          field="name"
          readValue={form.name || "(unnamed)"}
          editValue={form.name}
          editingField={editingField}
          onStartEdit={startInlineEdit}
          onChangeValue={(v) => onChange("name", v)}
          maxLength={AGENT_NAME_MAX_LENGTH}
        />
        <InlineSummaryRow
          label="Greeting"
          field="welcome"
          readValue={form.welcome || "—"}
          editValue={form.welcome}
          editingField={editingField}
          onStartEdit={startInlineEdit}
          onChangeValue={(v) => onChange("welcome", v)}
          inputType="textarea"
        />
      </div>

      <div className="flex flex-col gap-2">
        <span className="font-mono text-[9.5px] uppercase tracking-[.14em] text-v-muted">
          Language stacks
        </span>
        <LanguageStacksPanel stacks={stacks} onEdit={editStep("language")} />
      </div>

      <div className="flex flex-col border-t border-v-hairline pt-1">
        <SummaryRow label="Delivery" value={deliveryLabel} onEdit={editStep("delivery")} />
        <SummaryRow
          label="Knowledge base"
          value={
            form.kbEnabled && form.kbDocs.length > 0
              ? `On · ${form.kbDocs.length} doc(s)`
              : form.kbEnabled
                ? "Off · attach a document to activate"
                : "Off"
          }
          onEdit={editStep("agent")}
        />
        <SummaryRow
          label="Prompt"
          value={form.prompt.length > 90 ? `${form.prompt.slice(0, 90)}…` : form.prompt || "—"}
          onEdit={editStep("agent")}
        />
      </div>
    </div>
  );
}

export function ReviewStep({
  form,
  catalogs,
  onChange,
  mode = "create",
  agentId,
  onAgentSaved,
  onFinish,
  onEditStep,
}: ReviewStepProps) {
  const { session } = useAuth();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit() {
    setSaving(true);
    setError("");
    try {
      const saveCatalogs = await resolveSaveCatalogs(form);
      const payload = formToAgentCreatePayload(form, saveCatalogs);
      const agent = agentId ? await updateAgent(agentId, payload) : await createAgent(payload);
      onAgentSaved(agent);
    } catch (err) {
      setError(err instanceof Error ? err.message : `Couldn't ${agentId ? "save changes" : "create the agent"}.`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-5 animate-v-rise">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <p className="text-[13px] font-light text-v-muted">One listen catches a bad greeting before your callers do.</p>
        <span className="flex items-center gap-2">
          {mode === "create" && agentId ? (
            <Button variant="ghost" disabled={saving || catalogs.loading} onClick={handleSubmit}>
              {saving ? (
                <>
                  <Spinner light={false} /> Saving…
                </>
              ) : (
                "Save changes"
              )}
            </Button>
          ) : null}
          {mode === "create" && agentId ? (
            <Button onClick={onFinish}>Finish</Button>
          ) : (
            <Button
              data-tour="create-agent-button"
              disabled={!form.name || saving || catalogs.loading}
              onClick={handleSubmit}
            >
              {saving ? (
                <>
                  <Spinner /> {mode === "edit" ? "Saving…" : "Creating…"}
                </>
              ) : mode === "edit" ? (
                "Save changes"
              ) : (
                "Create agent"
              )}
            </Button>
          )}
        </span>
      </div>

      {error ? <span className="text-[12.5px] text-v-danger">{error}</span> : null}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_minmax(280px,360px)]">
        {agentId && session?.orgId ? (
          <BrowserCallSession orgId={session.orgId} agentId={agentId} agentName={form.name} />
        ) : (
          <div className="flex min-h-[260px] flex-col items-center justify-center gap-2 rounded-v-md border border-dashed border-v-line bg-white p-8 text-center">
            {saving ? (
              <>
                <Spinner light={false} />
                <span className="text-sm font-semibold text-v-fg">Creating your agent…</span>
              </>
            ) : (
              <>
                <span className="text-sm font-semibold text-v-fg">Test call</span>
                <span className="max-w-sm text-[13px] font-light text-v-muted">
                  Create the agent above to save your setup and start a live browser call here.
                </span>
              </>
            )}
          </div>
        )}
        <SelectionsSummary form={form} catalogs={catalogs} onChange={onChange} onEditStep={onEditStep} />
      </div>
    </div>
  );
}
