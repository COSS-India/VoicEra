import type {
  AgentApiResponse,
  AgentCreatePayload,
  AgentLanguageModels,
  AgentModelStack,
} from "@/lib/api-types";
import {
  buildConfigsForLanguageStack,
  EMPTY_LANGUAGE_STACK,
  stackFromApiConfigs,
  syncLanguageStacks,
  type SaveCatalogs,
} from "@/lib/language-stacks";
import { DEFAULT_FORM, type AgentForm } from "@/lib/wizard-data";

export function isAgentModelStack(value: unknown): value is AgentModelStack {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return "stt_config" in record && "tts_config" in record && "llm_config" in record;
}

/** Per-language stacks from language-keyed ``models`` (or a legacy flat primary stack). */
export function languageModelsFromAgent(agent: AgentApiResponse): AgentLanguageModels {
  const models = agent.config.models;
  if (!models || typeof models !== "object") return {};

  // Language-keyed map: at least one value looks like a stack.
  const values = Object.values(models);
  if (values.some(isAgentModelStack)) {
    const out: AgentLanguageModels = {};
    for (const [lang, stack] of Object.entries(models)) {
      if (isAgentModelStack(stack)) out[lang] = stack;
    }
    return out;
  }

  // Legacy flat primary stack mistakenly typed as the map.
  if (isAgentModelStack(models)) {
    const primary = agent.config.language.primary;
    return primary ? { [primary]: models } : {};
  }

  return {};
}

/** Resolve the primary-language model stack. */
export function primaryModelsFromAgent(agent: AgentApiResponse): AgentModelStack {
  const stacks = languageModelsFromAgent(agent);
  const primary = agent.config.language.primary;
  const fromLang = (primary && stacks[primary]) || Object.values(stacks)[0];
  if (fromLang) return fromLang;
  return { stt_config: {}, tts_config: {}, llm_config: {} };
}

export function formToAgentCreatePayload(
  form: AgentForm,
  saveCatalogs: SaveCatalogs,
): AgentCreatePayload {
  const primary = form.primaryLang || form.langs[0] || "en";
  const secondary = form.langs.filter((lang) => lang !== primary);
  const langs = [primary, ...secondary].filter(Boolean);

  const models: AgentLanguageModels = {};

  for (const lang of langs) {
    const stack = form.languageStacks[lang] ?? EMPTY_LANGUAGE_STACK;
    const { stt, tts, llm } = buildConfigsForLanguageStack(lang, stack, saveCatalogs);

    if (!stt || !tts || !llm) {
      throw new Error("Provider settings are still loading. Wait a moment and try again.");
    }

    models[lang] = {
      stt_config: stt,
      tts_config: tts,
      llm_config: llm,
    };
  }

  if (!models[primary]) {
    throw new Error("Primary language model configuration is missing.");
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
        vad: {
          confidence: form.vadConfidence,
          start_secs: form.vadStartSecs,
          stop_secs: form.vadStopSecs,
          min_volume: form.vadMinVolume,
        },
      },
      language: { primary, secondary },
      models,
      knowledge_base: {
        enabled: form.kbEnabled && form.kbDocs.length > 0,
        mode: "context",
        document_ids: form.kbDocs,
        top_k: 5,
      },
      custom_variables: form.customVariables,
    },
  };
}

/** Reverse of `formToAgentCreatePayload` — reconstructs the wizard's form shape from a saved agent. */
export function agentToForm(agent: AgentApiResponse): AgentForm {
  const { prompts, behaviour, language, knowledge_base } = agent.config;
  const stacks = languageModelsFromAgent(agent);
  const models = primaryModelsFromAgent(agent);
  const { stt_config: primaryStt, tts_config: primaryTts, llm_config: primaryLlm } = models;

  const langs = [language.primary, ...language.secondary].filter(Boolean);
  const languageStacks: AgentForm["languageStacks"] = {};
  const primaryFallback = stackFromApiConfigs(primaryStt, primaryTts, primaryLlm);

  for (const lang of langs) {
    const stack = stacks[lang] ?? (lang === language.primary ? models : undefined);
    if (stack) {
      languageStacks[lang] = stackFromApiConfigs(
        stack.stt_config,
        stack.tts_config,
        stack.llm_config,
      );
    } else {
      languageStacks[lang] = { ...primaryFallback };
    }
  }

  const synced = syncLanguageStacks(langs, languageStacks, language.primary, language.primary);

  return {
    ...DEFAULT_FORM,
    name: agent.name,
    purpose: agentPurposeFromApi(agent),
    welcome: prompts.greeting_message ?? DEFAULT_FORM.welcome,
    prompt: prompts.system_prompt ?? DEFAULT_FORM.prompt,
    customVariables: agent.config.custom_variables ?? {},
    ignoreGreetingSpeech: Boolean(behaviour.ignore_user_speech_before_greeting),
    langs,
    primaryLang: synced.primaryLang,
    languageStacks: synced.languageStacks,
    activeLang: synced.activeLang,
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
    vadConfidence: Number(
      (behaviour.vad as { confidence?: number } | undefined)?.confidence ??
        DEFAULT_FORM.vadConfidence,
    ),
    vadStartSecs: Number(
      (behaviour.vad as { start_secs?: number } | undefined)?.start_secs ??
        DEFAULT_FORM.vadStartSecs,
    ),
    vadStopSecs: Number(
      (behaviour.vad as { stop_secs?: number } | undefined)?.stop_secs ?? DEFAULT_FORM.vadStopSecs,
    ),
    vadMinVolume: Number(
      (behaviour.vad as { min_volume?: number } | undefined)?.min_volume ??
        DEFAULT_FORM.vadMinVolume,
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
