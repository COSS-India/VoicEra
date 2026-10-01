import type { CallLogItem, CallType } from "@/lib/api-types";

export type DatePreset = "all" | "today" | "7d" | "30d" | "custom";

/** Dograh-style range: real Date objects with local day bounds. */
export type DateRangeValue = { from: Date | null; to: Date | null };

export function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export function todayIso(): string {
  return isoDate(new Date());
}

/** Parse a YYYY-MM-DD input into a local Date (start or end of that day). */
export function dateFromInput(yyyyMmDd: string, endOfDay = false): Date | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(yyyyMmDd)) return null;
  const [y, m, d] = yyyyMmDd.split("-").map(Number);
  return endOfDay
    ? new Date(y, m - 1, d, 23, 59, 59, 999)
    : new Date(y, m - 1, d, 0, 0, 0, 0);
}

export function isCompleteRange(value: DateRangeValue): boolean {
  return Boolean(value.from && value.to && value.to.getTime() >= value.from.getTime());
}

/**
 * Same day-bound logic as dograh `getDatePresetValue` —
 * local midnight → local 23:59:59.999 so re-applying is deterministic.
 */
export function getDatePresetValue(preset: Exclude<DatePreset, "custom" | "all">): DateRangeValue {
  const now = new Date();
  const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0);
  const todayEnd = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999);

  if (preset === "today") return { from: todayStart, to: todayEnd };

  const from = new Date(todayStart);
  from.setDate(from.getDate() - (preset === "7d" ? 6 : 29));
  return { from, to: todayEnd };
}

export function rangeFromInputs(fromStr: string, toStr: string): DateRangeValue {
  return {
    from: dateFromInput(fromStr, false),
    to: dateFromInput(toStr, true),
  };
}

export function callTimeMs(call: CallLogItem): number {
  const raw = call.start_time_utc || call.created_at;
  if (!raw) return 0;
  const ts = Date.parse(raw);
  return Number.isFinite(ts) ? ts : 0;
}

export function filterAndSortCalls(
  calls: CallLogItem[],
  opts: {
    range: DateRangeValue | null;
    type: "all" | CallType;
    status: string;
    agentId: string;
  },
): CallLogItem[] {
  const fromMs = opts.range?.from?.getTime() ?? null;
  const toMs = opts.range?.to?.getTime() ?? null;

  const rows = calls.filter((c) => {
    if (opts.type !== "all" && c.call_type !== opts.type) return false;
    if (opts.status !== "all" && c.status !== opts.status) return false;
    if (opts.agentId && c.agent_id !== opts.agentId) return false;
    if (fromMs === null || toMs === null) return true;
    const ts = callTimeMs(c);
    if (!ts) return false;
    return ts >= fromMs && ts <= toMs;
  });

  return rows.sort((a, b) => {
    const diff = callTimeMs(b) - callTimeMs(a);
    return diff !== 0 ? diff : a.call_id.localeCompare(b.call_id);
  });
}
