import type { CallLogItem } from "@/lib/api-types";

/** Shorten a label for tight UI (agent cards, etc.). Full value stays available via title/tooltip. */
export function truncateLabel(value: string, max = 30): string {
  if (value.length <= max) return value;
  return `${value.slice(0, max)}...`;
}

/** No display-name field exists anywhere in the data model — only email — so
 * derive a readable name from the local part (e.g. "jane.doe" -> "Jane Doe"). */
export function nameFromEmail(email: string): string {
  const local = email.split("@")[0] ?? email;
  return local
    .split(/[._-]+/)
    .filter(Boolean)
    .map((part) => part[0]!.toUpperCase() + part.slice(1))
    .join(" ");
}

export function formatDuration(seconds?: number | null): string {
  if (!seconds && seconds !== 0) return "–";
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

/** "5h 35m" style — used for cumulative durations (e.g. total talk time),
 * distinct from formatDuration's "29s"/"1m 30s" for a single call. */
export function formatHoursMinutes(seconds?: number | null): string {
  if (!seconds && seconds !== 0) return "–";
  const totalMinutes = Math.round(seconds / 60);
  const h = Math.floor(totalMinutes / 60);
  const m = totalMinutes % 60;
  if (h === 0) return `${m}m`;
  return `${h}h ${m}m`;
}

export function formatDateTime(iso?: string | null): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "–";
  return d.toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatBytes(bytes?: number | null): string {
  if (!bytes && bytes !== 0) return "–";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// Calling codes long enough that a naive 2-digit split would be wrong — checked
// longest-first. Covers the common cases in this app (NANP, India, and the
// usual multi-digit codes); an unmatched number falls back to a 2-digit code,
// which is right for the large majority of real E.164 numbers.
const ONE_DIGIT_CALLING_CODES = new Set(["1", "7"]);
const THREE_DIGIT_CALLING_CODES = new Set([
  "971", "966", "965", "962", "961", "960", "886", "852", "234", "254", "255", "256", "212", "213", "216", "220",
]);

function splitCallingCode(digits: string): [string, string] {
  if (ONE_DIGIT_CALLING_CODES.has(digits.slice(0, 1))) return [digits.slice(0, 1), digits.slice(1)];
  if (THREE_DIGIT_CALLING_CODES.has(digits.slice(0, 3))) return [digits.slice(0, 3), digits.slice(3)];
  return [digits.slice(0, 2), digits.slice(2)];
}

/** Masks a phone number for at-a-glance display, e.g. "+918065480893" -> "+91
 * *****93" — keeps the calling code and last two digits, hides the rest. */
export function maskPhoneNumber(raw: string | null | undefined): string {
  if (!raw || raw === "-" || raw === "–") return "–";
  const m = /^\+(\d+)$/.exec(raw.trim().replace(/\s+/g, ""));
  if (!m) return raw;
  const [callingCode, national] = splitCallingCode(m[1]!);
  if (national.length <= 2) return `+${callingCode} ${national}`;
  return `+${callingCode}\u00A0*****${national.slice(-2)}`;
}

/** Only the person's real number gets masked — the agent's own linked number
 * stays visible. Websocket sessions have no real telephony numbers at all. */
export function displayToNumber(c: Pick<CallLogItem, "call_type" | "to_number">): string {
  if (c.call_type === "web") return "–";
  if (c.call_type === "outbound") return maskPhoneNumber(c.to_number);
  return c.to_number || "–";
}

export function displayFromNumber(c: Pick<CallLogItem, "call_type" | "from_number">): string {
  if (c.call_type === "web") return "–";
  if (c.call_type === "inbound") return maskPhoneNumber(c.from_number);
  return c.from_number || "–";
}
