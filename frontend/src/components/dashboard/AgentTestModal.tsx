"use client";

import { useMemo } from "react";
import Link from "next/link";
import { Pencil, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { BrowserCallSession } from "@/components/call/BrowserCallSession";
import type { AgentApiResponse } from "@/lib/api-types";
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
  const stt = agent.config.models.stt_config;
  const tts = agent.config.models.tts_config;
  const llm = agent.config.models.llm_config;
  const langs = [agent.config.language.primary, ...agent.config.language.secondary].filter(Boolean);

  const sttProvider = String(stt.provider ?? "");
  const sttModel = String(stt.model ?? "");
  const ttsProvider = String(tts.provider ?? "");
  const ttsModel = String(tts.model ?? "");
  const llmProvider = String(llm.provider ?? "");
  const llmModel = String(llm.model ?? "");
  const voice = String(tts.voice ?? "");

  const catalogs = useWizardCatalogs(langs, sttProvider, ttsProvider, llmProvider);

  const voices = voiceOptionsFromSettings(catalogs.ttsSettings, ttsModel, langs[0]);

  const langLabel = useMemo(
    () =>
      langs.length
        ? langs.map((id, i) => `${languageLabel(catalogs.languages, id)}${i === 0 ? " (primary)" : ""}`).join(" · ")
        : "—",
    [langs, catalogs.languages],
  );

  const stackRows = [
    { label: "Language", value: langLabel },
    {
      label: "STT",
      value: `${catalogs.sttProviders[sttProvider]?.name ?? sttProvider}${sttModel ? ` · ${sttModel}` : ""}`,
    },
    {
      label: "TTS",
      value: `${catalogs.ttsProviders[ttsProvider]?.name ?? ttsProvider}${ttsModel ? ` · ${ttsModel}` : ""}${
        voice ? ` · ${voices.find((v) => v.id === voice)?.name ?? voice}` : ""
      }`,
    },
    {
      label: "LLM",
      value: `${catalogs.llmProviders[llmProvider]?.name ?? llmProvider}${llmModel ? ` · ${llmModel}` : ""}`,
    },
  ];

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
              <span className="text-[13px] font-semibold">Agent stack</span>
              <Link href={`/agents/${agent.agent_id}/edit`}>
                <Button size="sm" variant="ghost">
                  <Pencil className="size-3.5" strokeWidth={1.75} />
                  Edit
                </Button>
              </Link>
            </div>

            <dl className="flex flex-col gap-3 text-[13px]">
              {stackRows.map((row) => (
                <div key={row.label} className="flex flex-col gap-0.5">
                  <dt className="font-mono text-[9.5px] uppercase tracking-[.1em] text-v-muted">{row.label}</dt>
                  <dd className="font-medium">{row.value}</dd>
                </div>
              ))}
            </dl>

            <div className="flex flex-col gap-1 border-t border-v-line pt-3">
              <span className="font-mono text-[9.5px] uppercase tracking-[.1em] text-v-muted">Prompt</span>
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
