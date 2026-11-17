import type { SlaMetric, SlaMetricStatus, SlaServiceStatus } from "@/lib/sla-types";
import { formatDateTime, formatDuration } from "@/lib/format";

const UNIT_SUFFIX: Record<string, string> = {
  pct: "%",
  ms: " ms",
  s: " s",
  min: " min",
  calls: "",
  mos: "",
  tokens_per_sec: " tokens/s",
};

function formatNumber(value: number, unit: string): string {
  if (unit === "pct" || unit === "mos") {
    return Number.isInteger(value) ? String(value) : value.toFixed(2).replace(/\.?0+$/, "");
  }
  if (unit === "ms" || unit === "calls") {
    return Math.round(value).toLocaleString("en-US");
  }
  if (unit === "s" || unit === "min") {
    return Number.isInteger(value)
      ? value.toLocaleString("en-US")
      : value.toFixed(1).replace(/\.0$/, "");
  }
  return value.toLocaleString("en-US");
}

function withUnit(value: number, unit: string): string {
  const formatted = formatNumber(value, unit);
  const suffix = UNIT_SUFFIX[unit] ?? (unit ? ` ${unit}` : "");
  if (unit === "calls") {
    return `${formatted} calls`;
  }
  return `${formatted}${suffix}`;
}

function comparatorPhrase(comparator: string): string {
  if (["gte", "or_more", ">="].includes(comparator)) return "or more";
  if (["lte", "or_less", "<="].includes(comparator)) return "or less";
  return "";
}

export function formatSlaTarget(metric: SlaMetric): string {
  const phrase = comparatorPhrase(metric.comparator);
  const value = withUnit(metric.target, metric.unit);
  return phrase ? `${value} ${phrase}` : value;
}

export function formatSlaActual(metric: SlaMetric): string {
  if (metric.status === "no_data" || metric.actual === null) {
    if (metric.key === "spare_gpu_takeover") return "No takeover";
    return "No data";
  }
  return withUnit(metric.actual, metric.unit);
}

export function metricRowHighlighted(status: SlaMetricStatus): boolean {
  return status === "missed" || status === "no_data";
}

export function metricDotClass(status: SlaMetricStatus): string {
  if (status === "met") return "bg-v-ok";
  if (status === "missed") return "bg-v-danger";
  return "bg-v-warn";
}

export function serviceBadgeTone(
  status: SlaServiceStatus,
): "live" | "danger" | "warn" | "neutral" {
  if (status === "working" || status === "running") return "live";
  if (status === "not_working") return "danger";
  if (status === "not_running") return "warn";
  return "neutral";
}

export function serviceStatusLabel(status: SlaServiceStatus): string {
  if (status === "working") return "Working";
  if (status === "not_working") return "Not working";
  if (status === "running") return "Running";
  if (status === "not_running") return "Not running";
  return "Unknown";
}

/** Short clock for hero / card footers, e.g. "10:42 AM". */
export function formatSlaClock(iso?: string | null): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "–";
  return new Intl.DateTimeFormat("en-GB", {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
    timeZoneName: "short",
  }).format(d);
}

export function formatSlaTimestamp(iso?: string | null): string {
  return formatDateTime(iso);
}

export function formatDurationSince(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return "–";
  return formatDuration(Math.max(0, Math.round(seconds)));
}
