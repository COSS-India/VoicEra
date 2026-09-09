"use client";

import { useEffect, useRef, useState } from "react";
import { Pencil } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { useAuth } from "@/components/AuthProvider";
import { createAgent, updateAgent } from "@/lib/api-client";
import { formToAgentCreatePayload } from "@/lib/agent-mapper";
import { BrowserCallSession } from "@/components/call/BrowserCallSession";
import type { AgentForm } from "@/lib/wizard-data";
import type { AgentApiResponse } from "@/lib/api-types";
import type { WizardCatalogs } from "@/lib/use-wizard-catalogs";
import { languageLabel, telephonyOptions, voiceOptionsFromSettings } from "@/lib/use-wizard-catalogs";

interface ReviewStepProps {
  form: AgentForm;
  catalogs: WizardCatalogs;
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

/** Read-only recap of every choice made across the wizard — the "what has
 * been chosen" list next to the test-call box. Each row's pencil jumps back
 * to the step that owns it. */
function SelectionsSummary({
  form,
  catalogs,
  onEditStep,
}: {
  form: AgentForm;
  catalogs: WizardCatalogs;
  onEditStep?: (stepId: string) => void;
}) {
  const voices = voiceOptionsFromSettings(catalogs.ttsSettings, form.ttsModel, form.langs[0]);
  const voiceLabel = voices.find((v) => v.id === form.voice)?.name ?? form.voice ?? "—";
  const llmName = catalogs.llmProviders[form.llmProvider]?.name ?? form.llmProvider ?? "—";
  const sttName = catalogs.sttProviders[form.sttProvider]?.name ?? form.sttProvider ?? "—";
  const ttsName = catalogs.ttsProviders[form.ttsProvider]?.name ?? form.ttsProvider ?? "—";
  const deliveryLabel =
    telephonyOptions(catalogs.telephonyProviders).find((d) => d.value === form.delivery)?.label ??
    "WebSocket — browser test";
  const langLabel =
    form.langs.map((id) => languageLabel(catalogs.languages, id)).join(", ") || "No languages";

  const editStep = (id: string) => (onEditStep ? () => onEditStep(id) : undefined);

  return (
    <div className="flex h-max flex-col rounded-v-md border border-v-line bg-white p-4.5">
      <span className="pb-2 font-mono text-[10px] uppercase tracking-[.16em] text-v-muted">What you&apos;ve chosen</span>
      <SummaryRow label="Name" value={form.name || "(unnamed)"} onEdit={editStep("name")} />
      <SummaryRow label="Greeting" value={form.welcome || "—"} onEdit={editStep("name")} />
      <SummaryRow
        label="Language"
        value={`${langLabel}${form.langs.length > 1 ? " · first is primary" : ""}`}
        onEdit={editStep("language")}
      />
      <SummaryRow
        label="STT"
        value={`${sttName}${form.sttModel ? ` · ${form.sttModel}` : ""}`}
        onEdit={editStep("language")}
      />
      <SummaryRow
        label="LLM"
        value={`${llmName}${form.llmModel ? ` · ${form.llmModel}` : ""}`}
        onEdit={editStep("language")}
      />
      <SummaryRow
        label="TTS"
        value={`${ttsName}${form.ttsModel ? ` · ${form.ttsModel}` : ""}${form.voice ? ` · ${voiceLabel}` : ""}`}
        onEdit={editStep("language")}
      />
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
        onEdit={editStep("prompt")}
      />
      <SummaryRow
        label="Prompt"
        value={form.prompt.length > 90 ? `${form.prompt.slice(0, 90)}…` : form.prompt || "—"}
        onEdit={editStep("prompt")}
      />
    </div>
  );
}

export function ReviewStep({
  form,
  catalogs,
  mode = "create",
  agentId,
  onAgentSaved,
  onFinish,
  onEditStep,
}: ReviewStepProps) {
  const { session } = useAuth();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  // Save the agent as soon as this step is reached instead of waiting for an
  // explicit click — so the test-call box is there to use right away. Once
  // `agentId` is set it's owned by the parent, so revisiting this step later
  // (after going back to tweak something) never re-attempts creation.
  const autoCreateAttempted = useRef(false);
  useEffect(() => {
    if (agentId || autoCreateAttempted.current || catalogs.loading) return;
    autoCreateAttempted.current = true;
    handleSubmit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId, catalogs.loading]);

  async function handleSubmit() {
    setSaving(true);
    setError("");
    try {
      const payload = formToAgentCreatePayload(form, catalogs);
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

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_300px]">
        {agentId && session?.orgId ? (
          <BrowserCallSession orgId={session.orgId} agentId={agentId} agentName={form.name} />
        ) : (
          <div className="flex min-h-[260px] flex-col items-center justify-center gap-2 rounded-v-md border border-dashed border-v-line bg-white p-8 text-center">
            {saving ? (
              <>
                <Spinner light={false} />
                <span className="text-sm font-semibold text-v-fg">Setting up your test call…</span>
              </>
            ) : (
              <>
                <span className="text-sm font-semibold text-v-fg">Couldn&apos;t set up the test call</span>
                <span className="max-w-sm text-[13px] font-light text-v-muted">
                  Try the button above again once everything looks right. Make sure provider credentials are
                  configured under Integrations.
                </span>
              </>
            )}
          </div>
        )}
        <SelectionsSummary form={form} catalogs={catalogs} onEditStep={onEditStep} />
      </div>
    </div>
  );
}
