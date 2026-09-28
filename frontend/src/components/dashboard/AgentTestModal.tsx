"use client";

import { useMemo } from "react";
import Link from "next/link";
import { Pencil, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { BrowserCallSession } from "@/components/call/BrowserCallSession";
import {
  formatServiceLine,
  LanguageStacksPanel,
  type LanguageStackSummary,
} from "@/components/dashboard/LanguageStacksPanel";
import type { AgentApiResponse } from "@/lib/api-types";
import { languageModelsFromAgent, primaryModelsFromAgent } from "@/lib/agent-mapper";
import {
  languageLabel,
  useWizardCatalogs,
  voiceOptionsFromSettings,
} from "@/lib/use-wizard-catalogs";

interface AgentTestModalProps {
  agent: AgentApiResponse;
  orgId: string;
  onClose: () => void;
}

export function AgentTestModal({ agent, orgId, onClose }: AgentTestModalProps) {
  const primary = agent.config.language.primary;
  const langs = [primary, ...agent.config.language.secondary].filter(Boolean);
  const stacksByLang = languageModelsFromAgent(agent);
  const primaryStack = primaryModelsFromAgent(agent);

  const sttProvider = String(primaryStack.stt_config.provider ?? "");
  const ttsProvider = String(primaryStack.tts_config.provider ?? "");
  const llmProvider = String(primaryStack.llm_config.provider ?? "");

  const catalogs = useWizardCatalogs(langs, sttProvider, ttsProvider, llmProvider);

  const stackSummaries: LanguageStackSummary[] = useMemo(() => {
    return langs.map((langId) => {
      const stack = stacksByLang[langId] ?? (langId === primary ? primaryStack : undefined);
      const stt = stack?.stt_config ?? {};
      const tts = stack?.tts_config ?? {};
      const llm = stack?.llm_config ?? {};

      const sttProv = String(stt.provider ?? "");
      const ttsProv = String(tts.provider ?? "");
      const llmProv = String(llm.provider ?? "");
      const ttsModel = String(tts.model ?? "");
      const voiceId = String(tts.voice ?? "");
      const voices = voiceOptionsFromSettings(catalogs.ttsSettings, ttsModel, langId);
      const voiceName = voiceId
        ? (voices.find((v) => v.id === voiceId)?.name ?? voiceId)
        : "";

      return {
        langId,
        label: languageLabel(catalogs.languages, langId),
        isPrimary: langId === primary,
        stt: formatServiceLine(
          catalogs.sttProviders[sttProv]?.name ?? sttProv,
          String(stt.model ?? ""),
        ),
        tts: formatServiceLine(
          catalogs.ttsProviders[ttsProv]?.name ?? ttsProv,
          ttsModel,
          voiceName,
        ),
        llm: formatServiceLine(
          catalogs.llmProviders[llmProv]?.name ?? llmProv,
          String(llm.model ?? ""),
        ),
      };
    });
  }, [
    langs,
    stacksByLang,
    primary,
    primaryStack,
    catalogs.languages,
    catalogs.sttProviders,
    catalogs.ttsProviders,
    catalogs.llmProviders,
    catalogs.ttsSettings,
  ]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--v-overlay)] p-6"
      onClick={onClose}
    >
      <div
        className="animate-v-rise flex max-h-[90vh] w-full max-w-4xl flex-col overflow-hidden rounded-v-md border border-v-line bg-white shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 border-b border-v-line px-5 py-4">
          <span className="flex flex-col gap-0.5">
            <span className="text-[15px] font-semibold">{agent.name}</span>
            <span className="text-xs font-light text-v-muted">Test call</span>
          </span>
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="flex size-8 cursor-pointer items-center justify-center rounded-v-sm text-v-muted transition-colors hover:bg-v-soft hover:text-v-fg"
          >
            <X className="size-4" strokeWidth={1.75} />
          </button>
        </div>

        <div className="flex flex-col gap-4 overflow-y-auto p-5 md:flex-row md:items-start">
          <div className="md:flex-[3]">
            <BrowserCallSession orgId={orgId} agentId={agent.agent_id} agentName={agent.name} />
          </div>

          <section className="flex flex-col gap-3 rounded-v-md border border-v-line bg-v-soft/40 p-4 md:flex-[2]">
            <div className="flex items-center justify-between gap-2">
              <span className="text-[13px] font-semibold">Language stacks</span>
              <Link href={`/agents/${agent.agent_id}/edit`}>
                <Button size="sm" variant="ghost">
                  <Pencil className="size-3.5" strokeWidth={1.75} />
                  Edit
                </Button>
              </Link>
            </div>

            <LanguageStacksPanel stacks={stackSummaries} />

            <div className="flex flex-col gap-1 border-t border-v-line pt-3">
              <span className="font-mono text-[9.5px] uppercase tracking-[.1em] text-v-muted">
                Prompt
              </span>
              <p className="max-h-48 overflow-y-auto whitespace-pre-wrap text-[12.5px] leading-relaxed text-v-fg">
                {agent.config.prompts.system_prompt.trim() || "No instructions set."}
              </p>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
