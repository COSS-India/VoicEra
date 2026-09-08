"use client";

import { use, useEffect, useState } from "react";
import { CheckCircle2, Clock, Phone, Settings, User } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { getAgent } from "@/lib/api-client";
import { agentToForm } from "@/lib/agent-mapper";
import { useToast } from "@/components/ui/useToast";
import type { AgentApiResponse } from "@/lib/api-types";
import type { AgentForm } from "@/lib/wizard-data";
import { AgentBasicsStep } from "@/components/wizard/AgentBasicsStep";
import { LanguageProvidersStep } from "@/components/wizard/LanguageProvidersStep";
import { DeliveryStep } from "@/components/wizard/DeliveryStep";
import { CallDetailsStep } from "@/components/wizard/CallDetailsStep";
import { ReviewStep } from "@/components/wizard/ReviewStep";
import { PromptLibraryDialog } from "@/components/wizard/PromptLibraryDialog";
import { SectionNav, type SectionNavItem } from "@/components/wizard/SectionNav";
import type { PromptModule } from "@/lib/prompt-modules";
import { useWizardCatalogs } from "@/lib/use-wizard-catalogs";
import { useSyncCustomVariables } from "@/lib/use-sync-custom-variables";

const STEPS: SectionNavItem[] = [
  { id: "agent", title: "Agent", subtitle: "Name, greeting & prompt", icon: User },
  { id: "language", title: "Language", subtitle: "STT · LLM · TTS", icon: Settings },
  { id: "delivery", title: "Delivery", subtitle: "Select provider", icon: Phone },
  { id: "call-details", title: "Call", subtitle: "Timeouts & silence", icon: Clock },
  { id: "review", title: "Review", subtitle: "Confirm", icon: CheckCircle2 },
];

function EditForm({
  agent,
  onSaved,
  onNotify,
}: {
  agent: AgentApiResponse;
  onSaved: (agent: AgentApiResponse) => void;
  onNotify: (title: string, note: string) => void;
}) {
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<AgentForm>(() => agentToForm(agent));
  const [libraryOpen, setLibraryOpen] = useState(false);

  const catalogs = useWizardCatalogs(form.langs, form.sttProvider, form.ttsProvider, form.llmProvider);

  const onChange = <K extends keyof AgentForm>(key: K, value: AgentForm[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  useSyncCustomVariables(form, onChange);

  const insertModule = (m: PromptModule) => {
    setForm((f) => ({
      ...f,
      prompt: f.prompt.includes(m.text) ? f.prompt : `${f.prompt}\n\n${m.text}`,
    }));
  };

  const jumpTo = (id: string) => {
    const idx = STEPS.findIndex((s) => s.id === id);
    if (idx >= 0) setStep(idx);
  };

  const currentId = STEPS[step]?.id ?? "agent";

  return (
    <div className="flex h-[calc(100vh-60px)] flex-col">
      <div className="shrink-0">
        <SectionNav items={STEPS} activeId={currentId} onSelect={jumpTo} eyebrow={agent.name} />
      </div>

      {/* Scrolls internally so the footer below never has to move — it's
          always the last flex child of this fixed-height shell. min-h-0 lets
          this flex-1 child actually shrink and scroll instead of growing past
          its container; deliberately not overflow-hidden on the outer shell,
          since that would clip the top/bottom bars' edge-to-edge bleed. */}
      <div className="scrollbar-hide flex min-h-0 flex-1 overflow-y-auto py-6">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-8">
          {catalogs.error ? (
            <div className="rounded-v-md border border-v-danger-line bg-v-danger-pale px-4 py-3 text-sm text-v-danger">
              {catalogs.error}
            </div>
          ) : null}

          {catalogs.loading ? (
            <div className="text-sm text-v-muted">Loading provider catalogs…</div>
          ) : (
            <>
              {currentId === "agent" ? (
                <AgentBasicsStep
                  form={form}
                  onChange={onChange}
                  onOpenLibrary={() => setLibraryOpen(true)}
                  onNotify={onNotify}
                />
              ) : null}

              {currentId === "language" ? (
                <LanguageProvidersStep form={form} catalogs={catalogs} onChange={onChange} />
              ) : null}

              {currentId === "delivery" ? <DeliveryStep form={form} catalogs={catalogs} onChange={onChange} /> : null}

              {currentId === "call-details" ? <CallDetailsStep form={form} onChange={onChange} /> : null}

              {currentId === "review" ? (
                <ReviewStep
                  form={form}
                  catalogs={catalogs}
                  mode="edit"
                  agentId={agent.agent_id}
                  onAgentSaved={(updated) => {
                    onSaved(updated);
                    onNotify("Saved", `${updated.name} was updated.`);
                  }}
                  onEditStep={jumpTo}
                />
              ) : null}
            </>
          )}
        </div>
      </div>

      {currentId !== "review" ? (
        <div className="-mx-[34px] -mb-[30px] flex shrink-0 border-t border-v-line bg-white px-[34px] py-5">
          <div className="mx-auto flex w-full max-w-3xl flex-wrap items-center justify-between gap-4">
            <Button variant="ghost" disabled={step === 0} onClick={() => setStep((s) => Math.max(0, s - 1))}>
              Back
            </Button>
            <span className="flex flex-1 flex-wrap items-center justify-end gap-4">
              <span className="text-xs font-light text-v-muted">
                Step {step + 1} of {STEPS.length}
              </span>
              <Button onClick={() => setStep((s) => Math.min(STEPS.length - 1, s + 1))}>Next</Button>
            </span>
          </div>
        </div>
      ) : null}

      <PromptLibraryDialog
        open={libraryOpen}
        onClose={() => setLibraryOpen(false)}
        currentPrompt={form.prompt}
        onInsert={insertModule}
      />
    </div>
  );
}

export default function EditAgentPage({ params }: { params: Promise<{ agentId: string }> }) {
  const { agentId } = use(params);
  const [agent, setAgent] = useState<AgentApiResponse | null>(null);
  const [loadError, setLoadError] = useState("");
  const { notify, toastNode } = useToast();

  useEffect(() => {
    let cancelled = false;
    getAgent(agentId)
      .then((a) => {
        if (!cancelled) setAgent(a);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err instanceof Error ? err.message : "Couldn't load agent.");
      });
    return () => {
      cancelled = true;
    };
  }, [agentId]);

  return (
    <main className="flex w-full flex-col gap-6">
      {loadError ? (
        <div className="rounded-v-md border border-v-danger-line bg-v-danger-pale px-4 py-3 text-sm text-v-danger">
          {loadError}
        </div>
      ) : agent ? (
        <EditForm agent={agent} onSaved={setAgent} onNotify={notify} />
      ) : (
        <div className="flex items-center gap-2 text-sm text-v-muted">
          <Spinner /> Loading agent…
        </div>
      )}

      {toastNode}
    </main>
  );
}
