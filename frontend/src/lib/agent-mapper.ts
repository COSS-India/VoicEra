import type { AgentApiResponse, AgentCreatePayload } from "@/lib/api-types";
import type { WizardCatalogs } from "@/lib/use-wizard-catalogs";
import { buildModelConfigsFromCatalogs } from "@/lib/use-wizard-catalogs";
import { DEFAULT_FORM, type AgentForm } from "@/lib/wizard-data";

export function formToAgentCreatePayload(
  form: AgentForm,
  catalogs: Pick<WizardCatalogs, "sttSettings" | "ttsSettings" | "llmSettings">,
): AgentCreatePayload {
  const primary = form.langs[0] ?? "en";
  const secondary = form.langs.slice(1);

  const { stt, tts, llm } = buildModelConfigsFromCatalogs(catalogs, {
    llmModel: form.llmModel,
    sttModel: form.sttModel,
    ttsModel: form.ttsModel,
    voice: form.voice,
    primaryLang: primary,
    sttExtra: form.sttExtra,
    ttsExtra: form.ttsExtra,
    llmExtra: form.llmExtra,
  });

  if (!stt || !tts || !llm) {
    throw new Error("Provider settings are still loading. Wait a moment and try again.");
  }

  const isTelephony = Boolean(form.delivery?.trim());

  return {
    name: form.name.trim(),
    agent_category: isTelephony ? "telephony" : "websocket",
    ...(isTelephony ? { telephony_provider: form.delivery } : {}),
    config: {
      schema_version: 1,
      prompts: {
        system_prompt:
          form.prompt.trim() || `You help callers with: ${form.purpose || form.name}.`,
        greeting_message: form.welcome.trim() || "Hello, how can I help you?",
      },
      behaviour: {
        interruption_min_words: form.interruptThreshold,
        user_silence_hangup_seconds: form.silenceTimeout,
        call_timeout_seconds: form.callLimit,
        ignore_user_speech_before_greeting: form.ignoreGreetingSpeech,
        hold_messages: form.holdPhrases.filter(Boolean),
        hold_message_timeout_seconds: form.holdMessageTimeoutSeconds,
        user_online_detection_enabled: form.checkStillThere,
        user_online_detection_message: form.onlineDetectionMessage,
        user_online_detection_seconds: form.onlineDetectionSeconds,
        user_online_detection_repeats: form.onlineDetectionRepeats,
        user_online_detection_closing_message: form.onlineDetectionClosingMessage,
        automatic_call_ending: {
          enabled: form.autoCallEndingEnabled,
          graceful_llm_call_ending: form.autoCallEndingGraceful,
        },
      },
      language: { primary, secondary },
      models: {
        stt_config: stt,
        tts_config: tts,
        llm_config: llm,
      },
      knowledge_base: {
        // The backend rejects enabled:true with zero document_ids — guard here
        // so flipping the "Use knowledge base" switch on before attaching any
        // documents (or a template that turns it on with none pre-attached)
        // never fails agent creation; it just stays effectively off until a
        // document is added.
        enabled: form.kbEnabled && form.kbDocs.length > 0,
        document_ids: form.kbDocs,
        top_k: 5,
      },
      custom_variables: form.customVariables,
    },
  };
}

/** Reverse of `formToAgentCreatePayload` — reconstructs the wizard's form shape from a saved agent. */
export function agentToForm(agent: AgentApiResponse): AgentForm {
  const { prompts, behaviour, language, models, knowledge_base } = agent.config;
  const { stt_config: stt, tts_config: tts, llm_config: llm } = models;

  return {
    ...DEFAULT_FORM,
    name: agent.name,
    purpose: agentPurposeFromApi(agent),
    welcome: prompts.greeting_message ?? DEFAULT_FORM.welcome,
    prompt: prompts.system_prompt ?? DEFAULT_FORM.prompt,
    customVariables: agent.config.custom_variables ?? {},
    ignoreGreetingSpeech: Boolean(behaviour.ignore_user_speech_before_greeting),
    langs: [language.primary, ...language.secondary].filter(Boolean),
    sttProvider: String(stt.provider ?? ""),
    sttModel: String(stt.model ?? ""),
    sttExtra: Object.fromEntries(
      Object.entries(stt).filter(([key]) => !["provider", "model", "language"].includes(key)),
    ),
    ttsProvider: String(tts.provider ?? ""),
    ttsModel: String(tts.model ?? ""),
    voice: String(tts.voice ?? ""),
    ttsExtra: Object.fromEntries(
      Object.entries(tts).filter(([key]) => !["provider", "model", "language", "voice"].includes(key)),
    ),
    llmProvider: String(llm.provider ?? ""),
    llmModel: String(llm.model ?? ""),
    llmExtra: Object.fromEntries(
      Object.entries(llm).filter(([key]) => !["provider", "model", "language"].includes(key)),
    ),
    kbEnabled: Boolean(knowledge_base.enabled),
    kbDocs: knowledge_base.document_ids ?? [],
    delivery: agent.agent_category === "telephony" ? String(agent.telephony?.provider ?? "") : "",
    interruptThreshold: Number(behaviour.interruption_min_words ?? DEFAULT_FORM.interruptThreshold),
    checkStillThere: Boolean(behaviour.user_online_detection_enabled),
    silenceTimeout: Number(behaviour.user_silence_hangup_seconds ?? DEFAULT_FORM.silenceTimeout),
    callLimit: Number(behaviour.call_timeout_seconds ?? DEFAULT_FORM.callLimit),
    holdPhrases: (behaviour.hold_messages as string[] | undefined)?.length
      ? (behaviour.hold_messages as string[])
      : DEFAULT_FORM.holdPhrases,
    holdMessageTimeoutSeconds: Number(
      behaviour.hold_message_timeout_seconds ?? DEFAULT_FORM.holdMessageTimeoutSeconds,
    ),
    onlineDetectionMessage: String(
      behaviour.user_online_detection_message ?? DEFAULT_FORM.onlineDetectionMessage,
    ),
    onlineDetectionSeconds: Number(
      behaviour.user_online_detection_seconds ?? DEFAULT_FORM.onlineDetectionSeconds,
    ),
    onlineDetectionRepeats: Number(
      behaviour.user_online_detection_repeats ?? DEFAULT_FORM.onlineDetectionRepeats,
    ),
    onlineDetectionClosingMessage: String(
      behaviour.user_online_detection_closing_message ?? DEFAULT_FORM.onlineDetectionClosingMessage,
    ),
    autoCallEndingEnabled: Boolean(
      (behaviour.automatic_call_ending as { enabled?: boolean } | undefined)?.enabled,
    ),
    autoCallEndingGraceful: Boolean(
      (behaviour.automatic_call_ending as { graceful_llm_call_ending?: boolean } | undefined)
        ?.graceful_llm_call_ending,
    ),
  };
}

export function agentPurposeFromApi(agent: {
  config: { prompts: { system_prompt: string } };
}): string {
  const prompt = agent.config.prompts.system_prompt.trim();
  if (!prompt) return "Voice agent";
  const first = prompt.split(/[.!?\n]/)[0]?.trim();
  return first && first.length <= 120 ? first : `${prompt.slice(0, 117)}…`;
}
