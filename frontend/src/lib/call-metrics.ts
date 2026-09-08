import type { CallMetricsBreakdown, CallMetricsResponse } from "@/lib/api-types";

export interface NormalizedTurn {
  turnNumber: number;
  durationSecs?: number;
  wasInterrupted?: boolean;
  sttMs?: number;
  llmTtfbMs?: number;
  ttsMs?: number;
  /** False for bot-initiated speech (e.g. an opening greeting) that has no
   * matching user utterance — excluded from averages/chart-worthy stats. */
  hasUserTurn: boolean;
}

export interface NormalizedCallMetrics {
  turns: NormalizedTurn[];
  turnCount?: number;
  interruptedTurnCount?: number;
  avgSttMs?: number;
  avgLlmTtfbMs?: number;
  avgTtsMs?: number;
  /** Server-computed (avg_stt_secs + avg_tts_secs + avg_llm_secs), whichever
   * of those are available — the overall per-turn pipeline latency, distinct
   * from roundTripAvgMs (the runtime's own end-to-end measurement). */
  avgLatencyMs?: number;
  maxSttMs?: number;
  maxLlmTtfbMs?: number;
  maxTtsMs?: number;
  firstBotSpeechMs?: number;
  roundTripAvgMs?: number;
  roundTripMinMs?: number;
  roundTripMaxMs?: number;
}

function classifyProcessor(processor: string): "stt" | "llm" | "tts" | null {
  const upper = processor.toUpperCase();
  if (upper.includes("STT")) return "stt";
  if (upper.includes("LLM")) return "llm";
  if (upper.includes("TTS")) return "tts";
  return null;
}

function msFromBreakdown(breakdown: CallMetricsBreakdown, kind: "stt" | "llm" | "tts"): number | undefined {
  const entry = breakdown.ttfb.find((t) => classifyProcessor(t.processor) === kind);
  return entry ? entry.duration_secs * 1000 : undefined;
}

function average(values: number[]): number | undefined {
  if (!values.length) return undefined;
  return values.reduce((a, b) => a + b, 0) / values.length;
}

function max(values: number[]): number | undefined {
  if (!values.length) return undefined;
  return Math.max(...values);
}

/** Merges the backend's raw {call_id, summary, transport, turns[], latencies}
 * payload into per-turn STT/LLM/TTS latency figures for charting/tabling.
 *
 * turns[] carries two records per turn_number (a "started" one and a
 * "duration_secs/was_interrupted" one on end) — these get merged by
 * turn_number. latencies.breakdowns[] aligns positionally with turns[]
 * (breakdowns[i] corresponds to turn_number i+1); a breakdown with a null
 * user_turn_start_time is bot-initiated speech (e.g. a greeting) rather than
 * a real user turn, so it's flagged via hasUserTurn but left out of averages. */
export function normalizeCallMetrics(metrics: CallMetricsResponse): NormalizedCallMetrics {
  const byTurnNumber = new Map<number, NormalizedTurn>();
  for (const record of metrics.turns) {
    const existing = byTurnNumber.get(record.turn_number) ?? {
      turnNumber: record.turn_number,
      hasUserTurn: false,
    };
    if (record.duration_secs !== undefined) existing.durationSecs = record.duration_secs;
    if (record.was_interrupted !== undefined) existing.wasInterrupted = record.was_interrupted;
    byTurnNumber.set(record.turn_number, existing);
  }

  const breakdowns = metrics.latencies.breakdowns ?? [];
  breakdowns.forEach((breakdown, index) => {
    const turnNumber = index + 1;
    const existing = byTurnNumber.get(turnNumber) ?? { turnNumber, hasUserTurn: false };
    existing.hasUserTurn = breakdown.user_turn_start_time != null;
    existing.sttMs = msFromBreakdown(breakdown, "stt");
    existing.llmTtfbMs = msFromBreakdown(breakdown, "llm");
    existing.ttsMs = msFromBreakdown(breakdown, "tts");
    byTurnNumber.set(turnNumber, existing);
  });

  const turns = [...byTurnNumber.values()].sort((a, b) => a.turnNumber - b.turnNumber);
  const userTurns = turns.filter((t) => t.hasUserTurn);

  const sttValues = userTurns.map((t) => t.sttMs).filter((v): v is number => v !== undefined);
  const llmValues = userTurns.map((t) => t.llmTtfbMs).filter((v): v is number => v !== undefined);
  const ttsValues = userTurns.map((t) => t.ttsMs).filter((v): v is number => v !== undefined);

  return {
    turns,
    turnCount: metrics.summary.turn_count,
    interruptedTurnCount: metrics.summary.interrupted_turn_count,
    avgSttMs: average(sttValues),
    avgLlmTtfbMs: average(llmValues),
    avgTtsMs: average(ttsValues),
    maxSttMs: max(sttValues),
    maxLlmTtfbMs: max(llmValues),
    maxTtsMs: max(ttsValues),
    firstBotSpeechMs:
      metrics.latencies.first_bot_speech_secs !== undefined
        ? metrics.latencies.first_bot_speech_secs * 1000
        : undefined,
    roundTripAvgMs:
      metrics.summary.user_bot_latency_avg_secs !== undefined
        ? metrics.summary.user_bot_latency_avg_secs * 1000
        : undefined,
    roundTripMinMs:
      metrics.summary.user_bot_latency_min_secs !== undefined
        ? metrics.summary.user_bot_latency_min_secs * 1000
        : undefined,
    roundTripMaxMs:
      metrics.summary.user_bot_latency_max_secs !== undefined
        ? metrics.summary.user_bot_latency_max_secs * 1000
        : undefined,
    avgLatencyMs:
      metrics.summary.avg_latency_secs != null ? metrics.summary.avg_latency_secs * 1000 : undefined,
  };
}

export function formatMs(value: number | undefined): string {
  return value !== undefined ? `${Math.round(value)} ms` : "—";
}

export function formatSecs(value: number | undefined, digits = 1): string {
  return value !== undefined ? `${value.toFixed(digits)}s` : "—";
}
