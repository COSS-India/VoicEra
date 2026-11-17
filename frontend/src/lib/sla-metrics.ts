import type {
  SlaMetric,
  SlaMetricsPayload,
  SlaTelemetryResponse,
} from "@/lib/sla-types";

export type PerformanceSectionId =
  | "availability"
  | "speed"
  | "orchestration"
  | "errors"
  | "capacity"
  | "telephony_quality"
  | "other";

export type PerformanceSection = {
  id: PerformanceSectionId;
  title: string;
  metrics: SlaMetric[];
};

const SECTION_KEYS: Record<Exclude<PerformanceSectionId, "other">, string[]> = {
  availability: [
    "overall_availability",
    "peak_hours_availability",
    "unplanned_downtime",
    "health_check_success",
    "healthy_gpu_uptime",
    "spare_gpu_takeover",
    "model_ready_after_restart",
    "telephony_availability",
    "telephony_peak_hours_availability",
  ],
  speed: ["stt_p50", "stt_p95", "tts_p50", "tts_p95", "llm_p50", "llm_p95"],
  orchestration: [
    "orchestration_overhead_p95",
    "end_to_end_p50",
    "end_to_end_p95",
  ],
  errors: [
    "error_rate",
    "timeout_rate",
    "llm_output_speed",
    "agent_session_start_success",
    "unexpected_call_drops",
  ],
  capacity: [
    "calls_live_now",
    "peak_calls",
    "calls_rejected_below_limit",
    "peak_gpu_load",
    "peak_gpu_load_duration",
    "telephony_connections_reserved",
    "committed_capacity",
  ],
  telephony_quality: [
    "call_setup_success",
    "post_dial_delay_p95",
    "connection_time_p95",
    "one_way_media_delay",
    "jitter",
    "packet_loss",
    "audio_quality_mos",
    "carrier_side_call_drops",
  ],
};

const SECTION_TITLES: Record<PerformanceSectionId, string> = {
  availability: "Availability",
  speed: "Speed",
  orchestration: "Orchestration",
  errors: "Errors",
  capacity: "Capacity",
  telephony_quality: "Telephony quality",
  other: "Other",
};

const SECTION_ORDER: Exclude<PerformanceSectionId, "other">[] = [
  "availability",
  "speed",
  "orchestration",
  "errors",
  "capacity",
  "telephony_quality",
];

function metricsList(payload: SlaMetricsPayload | null | undefined): SlaMetric[] {
  return payload?.metrics ?? [];
}

/** Merge campaign telemetry with deployment GPU / telephony / availability. Later sources win on key clash so GPU health overrides availability stubs. */
export function buildPerformanceMetrics(
  telemetry: SlaTelemetryResponse | null,
  gpu: SlaMetricsPayload | null,
  telephony: SlaMetricsPayload | null,
  availability: SlaMetricsPayload | null,
): SlaMetric[] {
  const byKey = new Map<string, SlaMetric>();
  for (const row of [
    ...metricsList(availability),
    ...(telemetry?.metrics ?? []),
    ...metricsList(telephony),
    ...metricsList(gpu),
  ]) {
    byKey.set(row.key, row);
  }
  return Array.from(byKey.values());
}

export function groupPerformanceSections(metrics: SlaMetric[]): PerformanceSection[] {
  const byKey = new Map(metrics.map((m) => [m.key, m]));
  const used = new Set<string>();
  const sections: PerformanceSection[] = [];

  for (const id of SECTION_ORDER) {
    const rows: SlaMetric[] = [];
    for (const key of SECTION_KEYS[id]) {
      const row = byKey.get(key);
      if (row) {
        rows.push(row);
        used.add(key);
      }
    }
    if (rows.length > 0) {
      sections.push({ id, title: SECTION_TITLES[id], metrics: rows });
    }
  }

  const leftover = metrics.filter((m) => !used.has(m.key));
  if (leftover.length > 0) {
    sections.push({
      id: "other",
      title: SECTION_TITLES.other,
      metrics: leftover,
    });
  }

  return sections;
}

export function countMissedTargets(metrics: SlaMetric[]): {
  missed: number;
  total: number;
} {
  return {
    missed: metrics.filter((m) => m.status === "missed").length,
    total: metrics.length,
  };
}
