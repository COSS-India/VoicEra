export interface TranscriptLine {
  role: "user" | "assistant" | string;
  timestamp: string;
  content: string;
  /** Seconds from the start of the recording, relative to the first line
   * (best estimate — see parseTranscript). */
  offsetSeconds: number;
}

/** pipecat writes `message.timestamp` as a full ISO 8601 string (e.g.
 * `2026-08-31T10:53:09.443+00:00`), via time_now_iso8601() — not a bare
 * `HH:MM:SS`. Date.parse handles that natively; the manual HH:MM:SS split is
 * a defensive fallback for any older/malformed data, not the primary path. */
export function parseTimestampMs(ts: string): number | null {
  const parsed = Date.parse(ts);
  if (Number.isFinite(parsed)) return parsed;
  const parts = ts.split(":").map(Number);
  if (parts.length === 3 && parts.every((p) => Number.isFinite(p))) {
    return (parts[0]! * 3600 + parts[1]! * 60 + parts[2]!) * 1000;
  }
  return null;
}

export function formatClockLabel(ts: string): string {
  const ms = Date.parse(ts);
  if (!Number.isFinite(ms)) return ts;
  return new Date(ms).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** Parses the runtime's transcript.txt format: `call_id=...`, `---`, then
 * `[timestamp] role: content` lines. See apps/runtime/services/storage/transcript.py.
 *
 * There's no shared clock between the transcript's per-line timestamps and the
 * recording's own start time worth trusting across services, so offsets are
 * anchored to the FIRST line at t=0 and computed from deltas between lines,
 * which come from the same clock and are reliable relative to each other even
 * if their absolute mapping to the recording isn't exact.
 */
export function parseTranscript(raw: string): TranscriptLine[] {
  const rows: { role: string; timestamp: string; content: string; ms: number | null }[] = [];
  for (const line of raw.split("\n")) {
    const m = /^\[([^\]]+)]\s*([^:\]]+):\s*(.*)$/.exec(line);
    if (!m) continue;
    const timestamp = m[1]!;
    rows.push({ role: m[2]!, timestamp, content: m[3]!, ms: parseTimestampMs(timestamp) });
  }
  const base = rows.find((r) => r.ms !== null)?.ms ?? 0;
  return rows.map((r) => ({
    role: r.role,
    timestamp: r.timestamp,
    content: r.content,
    offsetSeconds: r.ms === null ? 0 : Math.max(0, (r.ms - base) / 1000),
  }));
}

/** Base codes the backend translates into — mirrors SUPPORTED_TARGET_LANGS in
 * apps/api/app/services/translation_service.py (built from
 * apps/providers/languages.py; 'or' is the ISO code for Odia). The backend
 * rejects anything else with 422, so an unsupported browser language falls
 * back to English rather than making the Translate button fail. */
export const SUPPORTED_TRANSLATION_LANGS: ReadonlySet<string> = new Set([
  "hi", "bn", "ta", "te", "gu", "kn", "ml", "mr", "pa", "or", "as", "ur", "ne", "sa",
  "brx", "doi", "kok", "ks", "mai", "mni", "sat", "sd", "bh", "bho", "bgc", "hne", "en",
]);

/** The viewer's browser language as a translation target, or "en" if the
 * backend doesn't serve it. */
export function translationTargetLang(browserLang?: string): string {
  const raw = browserLang ?? (typeof navigator !== "undefined" ? navigator.language : "") ?? "";
  const base = (raw || "en").split("-")[0]!.toLowerCase();
  return SUPPORTED_TRANSLATION_LANGS.has(base) ? base : "en";
}
