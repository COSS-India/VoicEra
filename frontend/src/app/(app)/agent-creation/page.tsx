"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { CheckCircle2, Clock, MessageSquare, Phone, Settings, User } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { StartStep } from "@/components/wizard/StartStep";
import { AgentBasicsStep } from "@/components/wizard/AgentBasicsStep";
import { LanguageProvidersStep } from "@/components/wizard/LanguageProvidersStep";
import { DeliveryStep } from "@/components/wizard/DeliveryStep";
import { CallDetailsStep } from "@/components/wizard/CallDetailsStep";
import { ReviewStep } from "@/components/wizard/ReviewStep";
import { PromptLibraryDialog } from "@/components/wizard/PromptLibraryDialog";
import { SectionNav, type SectionNavItem } from "@/components/wizard/SectionNav";
import { useToast } from "@/components/ui/useToast";
import { AgentForm, AgentTemplate, DEFAULT_FORM } from "@/lib/wizard-data";
import { PromptModule } from "@/lib/prompt-modules";
import { useSyncCustomVariables } from "@/lib/use-sync-custom-variables";
import {
  defaultModelFromSettings,
  modelOptionsFromSettings,
  pickFirstProvider,
  useWizardCatalogs,
  voiceOptionsFromSettings,
} from "@/lib/use-wizard-catalogs";

const STEPS: SectionNavItem[] = [
  { id: "start", title: "Setup", subtitle: "Start from scratch", icon: MessageSquare },
  { id: "agent", title: "Agent", subtitle: "Name, greeting & prompt", icon: User },
  { id: "language", title: "Engine", subtitle: "STT · LLM · TTS", icon: Settings },
  { id: "delivery", title: "Delivery", subtitle: "Select provider", icon: Phone },
  { id: "call-details", title: "Call", subtitle: "Timeouts & silence", icon: Clock },
  { id: "review", title: "Review", subtitle: "Confirm", icon: CheckCircle2 },
];

const NEXT_LABEL: Record<string, string> = {
  agent: "Next — engine & providers",
  language: "Next — delivery",
  delivery: "Next — call details",
  "call-details": "Next — review",
};

function providerStillValid(list: Record<string, unknown>, id: string): boolean {
  return Boolean(id && id in list);
}

export default function AgentCreationPage() {
  const router = useRouter();
  const [step, setStep] = useState(0);
  // Furthest step ever reached — going back to re-check an earlier step
  // shouldn't re-lock the ones already filled in ahead of it.
  const [maxStep, setMaxStep] = useState(0);
  const [form, setForm] = useState<AgentForm>(DEFAULT_FORM);
  const [libraryOpen, setLibraryOpen] = useState(false);
  // The draft agent created as soon as Review is reached — lives here (not in
  // ReviewStep) so it survives navigating away from Review and back.
  const [draftAgentId, setDraftAgentId] = useState<string | null>(null);

  const catalogs = useWizardCatalogs(
    form.langs,
    form.sttProvider,
    form.ttsProvider,
    form.llmProvider,
  );
  const { notify, toastNode } = useToast();

  const onChange = <K extends keyof AgentForm>(key: K, value: AgentForm[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  useEffect(() => {
    setMaxStep((m) => Math.max(m, step));
  }, [step]);

  useSyncCustomVariables(form, onChange);

  // Pick a first provider whenever one is missing (fresh form, or a template
  // that only sets languages) or the current pick no longer matches the
  // language-filtered catalog — not just on "became invalid", which used to
  // skip straight past an empty provider forever.
  useEffect(() => {
    if (catalogs.loading || form.langs.length === 0) return;
    setForm((f) => {
      let next = { ...f };
      if (!providerStillValid(catalogs.sttProviders, f.sttProvider)) {
        next = { ...next, sttProvider: pickFirstProvider(catalogs.sttProviders) };
      }
      if (!providerStillValid(catalogs.ttsProviders, f.ttsProvider)) {
        next = { ...next, ttsProvider: pickFirstProvider(catalogs.ttsProviders) };
      }
      if (!providerStillValid(catalogs.llmProviders, f.llmProvider)) {
        next = { ...next, llmProvider: pickFirstProvider(catalogs.llmProviders) };
      }
      return next;
    });
  }, [
    catalogs.loading,
    catalogs.sttProviders,
    catalogs.ttsProviders,
    catalogs.llmProviders,
    form.langs,
  ]);

  useEffect(() => {
    if (catalogs.llmSettings) {
      const model = defaultModelFromSettings(catalogs.llmSettings);
      const models = modelOptionsFromSettings(catalogs.llmSettings);
      if (model && !form.llmModel) onChange("llmModel", model);
      else if (form.llmModel && !models.some((m) => m.value === form.llmModel) && models[0]) {
        onChange("llmModel", models[0].value);
      }
    }
  }, [catalogs.llmSettings, form.llmModel]);

  useEffect(() => {
    if (catalogs.ttsSettings) {
      // Voice options are per (model, language) via `capabilities` — omitting
      // these resolved against the wrong (arbitrary first) language, so a
      // validly-picked voice for the real language kept getting judged "not
      // in the list" and silently reset on every render.
      const voices = voiceOptionsFromSettings(catalogs.ttsSettings, form.ttsModel, form.langs[0]);
      if (voices.length && !form.voice) onChange("voice", voices[0]!.id);
      else if (form.voice && !voices.some((v) => v.id === form.voice) && voices[0]) {
        onChange("voice", voices[0].id);
      }
    }
  }, [catalogs.ttsSettings, form.voice, form.ttsModel, form.langs]);

  useEffect(() => {
    if (catalogs.sttSettings) {
      const model = defaultModelFromSettings(catalogs.sttSettings);
      const models = modelOptionsFromSettings(catalogs.sttSettings);
      if (model && !form.sttModel) onChange("sttModel", model);
      else if (form.sttModel && !models.some((m) => m.value === form.sttModel) && models[0]) {
        onChange("sttModel", models[0].value);
      }
    }
  }, [catalogs.sttSettings, form.sttModel]);

  useEffect(() => {
    if (catalogs.ttsSettings) {
      const model = defaultModelFromSettings(catalogs.ttsSettings);
      const models = modelOptionsFromSettings(catalogs.ttsSettings);
      if (model && !form.ttsModel) onChange("ttsModel", model);
      else if (form.ttsModel && !models.some((m) => m.value === form.ttsModel) && models[0]) {
        onChange("ttsModel", models[0].value);
      }
    }
  }, [catalogs.ttsSettings, form.ttsModel]);

  const jumpTo = (id: string) => {
    const idx = STEPS.findIndex((s) => s.id === id);
    if (idx >= 0) setStep(idx);
  };

  const useTemplate = (t: AgentTemplate) => {
    setForm((f) => ({ ...f, ...t.set }));
    jumpTo("review");
  };

  const insertModule = (m: PromptModule) => {
    setForm((f) => ({
      ...f,
      prompt: f.prompt.includes(m.text) ? f.prompt : `${f.prompt}\n\n${m.text}`,
    }));
  };

  const languageProvidersReady =
    form.langs.length > 0 &&
    Boolean(form.sttProvider) &&
    Boolean(form.ttsProvider) &&
    Boolean(form.llmProvider) &&
    Boolean(form.llmModel);

  const currentId = STEPS[step]?.id ?? "start";
  const showFooter = currentId !== "start" && currentId !== "review";

  const canAdvance =
    (currentId !== "agent" || Boolean(form.name)) &&
    (currentId !== "language" || languageProvidersReady) &&
    !catalogs.loading;

  const advanceBlockedReason =
    currentId === "agent" && !form.name
      ? "Give it a name to continue"
      : currentId === "language" && !languageProvidersReady
        ? "Select a language and STT/TTS/LLM providers to continue"
        : undefined;

  return (
    <main className="flex h-[calc(100vh-60px)] w-full flex-col">
      <div className="shrink-0">
        <SectionNav
          items={STEPS.map((s, i) => ({ ...s, disabled: i > maxStep }))}
          activeId={currentId}
          onSelect={(id) => jumpTo(id)}
          eyebrow="Create an agent"
        />
      </div>

      {/* Scrolls internally so the footer below never has to move — it's
          always the last flex child of this fixed-height shell, at the same
          screen position on every step regardless of that step's content
          height. min-h-0 is required for a flex-1 child to actually shrink
          and scroll instead of growing past its container (the usual
          flexbox-overflow gotcha) — deliberately not overflow-hidden on
          <main> itself, since that would clip the top/bottom bars' bleed. */}
      <div className="scrollbar-hide flex min-h-0 flex-1 overflow-y-auto py-6">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-8">
          {catalogs.error ? (
            <div className="rounded-v-md border border-v-danger-line bg-v-danger-pale px-4 py-3 text-sm text-v-danger">
              {catalogs.error}
            </div>
          ) : null}

          {currentId === "start" ? (
            <StartStep onStartScratch={() => setStep(1)} onUseTemplate={useTemplate} />
          ) : null}

          {catalogs.loading && currentId !== "start" ? (
            <div className="text-sm text-v-muted">Loading provider catalogs…</div>
          ) : null}

          {currentId === "agent" && !catalogs.loading ? (
            <AgentBasicsStep
              form={form}
              onChange={onChange}
              onOpenLibrary={() => setLibraryOpen(true)}
              onNotify={notify}
            />
          ) : null}

          {currentId === "language" && !catalogs.loading ? (
            <LanguageProvidersStep form={form} catalogs={catalogs} onChange={onChange} />
          ) : null}

          {currentId === "delivery" && !catalogs.loading ? (
            <DeliveryStep form={form} catalogs={catalogs} onChange={onChange} />
          ) : null}

          {currentId === "call-details" && !catalogs.loading ? (
            <CallDetailsStep form={form} onChange={onChange} />
          ) : null}

          {currentId === "review" && !catalogs.loading ? (
            <ReviewStep
              form={form}
              catalogs={catalogs}
              agentId={draftAgentId}
              onAgentSaved={(agent) => setDraftAgentId(agent.agent_id)}
              onFinish={() => router.push("/dashboard")}
              onEditStep={jumpTo}
            />
          ) : null}
        </div>
      </div>

      {showFooter ? (
        <div className="-mx-[34px] -mb-[30px] flex shrink-0 border-t border-v-line bg-white px-[34px] py-5">
          <div className="mx-auto flex w-full max-w-3xl flex-wrap items-center justify-between gap-4">
            <Button variant="ghost" onClick={() => setStep((s) => Math.max(0, s - 1))}>
              Back
            </Button>
            <span className="flex flex-1 flex-wrap items-center justify-end gap-4">
              <span className="text-xs font-light text-v-muted">
                Step {step + 1} of {STEPS.length - 1} · you can change anything later
              </span>
              <Button
                data-tour="wizard-next-button"
                disabled={!canAdvance}
                title={advanceBlockedReason}
                onClick={() => setStep((s) => Math.min(STEPS.length - 1, s + 1))}
              >
                {NEXT_LABEL[currentId] ?? "Next"}
              </Button>
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
      {toastNode}
    </main>
  );
}
