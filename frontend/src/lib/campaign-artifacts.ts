import type { CallResponseStatus, CampaignRunItem } from "@/lib/api-types";

/** Page size for campaign runs tables / analytics dialog. */
export const CAMPAIGN_RUNS_PAGE_SIZE = 25;

/** Canonical call dispositions — keep in sync with `CallResponseStatus`. */
export const CALL_RESPONSE_STATUSES: readonly CallResponseStatus[] = [
  "pending",
  "answered",
  "busy",
  "no_answer",
  "failed",
  "cancelled",
] as const;

/** Disposition that counts as a successful connection (matches backend). */
export const CONNECTED_CALL_RESPONSE: CallResponseStatus = "answered";

export type DispositionFilterOption = { value: string; label: string };

export function humanizeToken(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function dispositionFilterOptions(): DispositionFilterOption[] {
  return [
    { value: "", label: "All dispositions" },
    ...CALL_RESPONSE_STATUSES.map((value) => ({
      value,
      label: humanizeToken(value),
    })),
  ];
}

export function hasArtifactUrl(url: unknown): boolean {
  return typeof url === "string" && url.trim().length > 0;
}

export type DispositionBreakdownRow = {
  key: string;
  count: number;
  pct: number;
};

export function dispositionBreakdown(
  byCallResponse: Record<string, number> | null | undefined,
): DispositionBreakdownRow[] {
  const map = byCallResponse ?? {};
  const total = Object.values(map).reduce((sum, n) => sum + n, 0);
  if (total <= 0) return [];
  return Object.entries(map)
    .sort((a, b) => b[1] - a[1])
    .map(([key, count]) => ({
      key,
      count,
      pct: Math.round((count / total) * 100),
    }));
}

export function runsWithTranscript(runs: CampaignRunItem[]): CampaignRunItem[] {
  return runs.filter((r) => r.call_id && hasArtifactUrl(r.transcript_url));
}

export function runsWithRecording(runs: CampaignRunItem[]): CampaignRunItem[] {
  return runs.filter((r) => r.call_id && hasArtifactUrl(r.recording_url));
}

export function campaignExportBasename(campaignId: string, kind: string): string {
  return `campaign_${campaignId}_${kind}`;
}

export function transcriptZipEntryPath(callId: string): string {
  return `transcripts/${callId}.txt`;
}

export function recordingZipEntryPath(callId: string, contentType?: string): string {
  return `recordings/${callId}.${audioExtensionFromContentType(contentType)}`;
}

export function singleTranscriptFilename(callId: string): string {
  return `${callId}-transcript.txt`;
}

export function singleRecordingFilename(callId: string, contentType?: string): string {
  return `${callId}.${audioExtensionFromContentType(contentType)}`;
}

export function audioExtensionFromContentType(contentType?: string): string {
  const type = (contentType || "").toLowerCase();
  if (type.includes("mpeg") || type.includes("mp3")) return "mp3";
  if (type.includes("ogg")) return "ogg";
  if (type.includes("webm")) return "webm";
  if (type.includes("wav") || type.includes("wave")) return "wav";
  return "wav";
}

export function defaultAudioContentType(contentType?: string): string {
  return contentType && contentType.trim() ? contentType : "audio/wav";
}
