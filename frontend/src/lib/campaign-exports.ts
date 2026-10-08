import { fetchCallRecordingBlob, fetchCallTranscriptText } from "@/lib/api/calls";
import {
  downloadCampaignReport,
  listAllCampaignRuns,
} from "@/lib/api/campaigns";
import type {
  CallResponseStatus,
  CampaignApiResponse,
  CampaignRunItem,
} from "@/lib/api-types";
import { downloadBlob } from "@/lib/report";
import { downloadZip } from "@/lib/zip";

export const CAMPAIGN_RUNS_PAGE_SIZE = 25;

const CALL_RESPONSE_STATUSES: readonly CallResponseStatus[] = [
  "pending",
  "answered",
  "busy",
  "no_answer",
  "failed",
  "cancelled",
];

export function humanizeToken(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function dispositionFilterOptions(): { value: string; label: string }[] {
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

export function dispositionBreakdown(
  byCallResponse: Record<string, number> | null | undefined,
): Array<{ key: string; count: number; pct: number }> {
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

function audioExtension(contentType?: string): string {
  const type = (contentType || "").toLowerCase();
  if (type.includes("mpeg") || type.includes("mp3")) return "mp3";
  if (type.includes("ogg")) return "ogg";
  if (type.includes("webm")) return "webm";
  return "wav";
}

export type CampaignExportKind = "report" | "transcripts" | "recordings";

export type CampaignExportResult = {
  kind: CampaignExportKind;
  title: string;
  note: string;
};

async function collectZipEntries<T>(
  runs: CampaignRunItem[],
  collect: (run: CampaignRunItem) => Promise<{ path: string; data: T } | null>,
): Promise<Array<{ path: string; data: T }>> {
  const entries: Array<{ path: string; data: T }> = [];
  for (const run of runs) {
    try {
      const entry = await collect(run);
      if (entry) entries.push(entry);
    } catch {
      /* skip missing / failed artifact */
    }
  }
  return entries;
}

export async function exportCampaignReport(
  campaign: CampaignApiResponse,
): Promise<CampaignExportResult> {
  const blob = await downloadCampaignReport(campaign.campaign_id);
  downloadBlob(blob, "text/csv", `campaign_${campaign.campaign_id}_report.csv`);
  return {
    kind: "report",
    title: "Report downloaded",
    note: `CSV report for ${campaign.name}.`,
  };
}

export async function exportCampaignTranscriptsZip(
  campaign: CampaignApiResponse,
): Promise<CampaignExportResult> {
  const allRuns = await listAllCampaignRuns(campaign.campaign_id);
  const candidates = allRuns.filter((r) => r.call_id && hasArtifactUrl(r.transcript_url));
  const entries = await collectZipEntries(candidates, async (run) => {
    const callId = String(run.call_id);
    const text = await fetchCallTranscriptText(callId);
    return { path: `transcripts/${callId}.txt`, data: text };
  });

  if (entries.length === 0) {
    return {
      kind: "transcripts",
      title: "No transcripts",
      note: "None of the calls in this campaign have a transcript yet.",
    };
  }

  await downloadZip(`campaign_${campaign.campaign_id}_transcripts.zip`, entries);
  return {
    kind: "transcripts",
    title: "Transcripts downloaded",
    note: `${entries.length} of ${candidates.length} transcripts in ZIP.`,
  };
}

export async function exportCampaignRecordingsZip(
  campaign: CampaignApiResponse,
): Promise<CampaignExportResult> {
  const allRuns = await listAllCampaignRuns(campaign.campaign_id);
  const candidates = allRuns.filter((r) => r.call_id && hasArtifactUrl(r.recording_url));
  const entries = await collectZipEntries(candidates, async (run) => {
    const callId = String(run.call_id);
    const blob = await fetchCallRecordingBlob(callId);
    return {
      path: `recordings/${callId}.${audioExtension(blob.type)}`,
      data: await blob.arrayBuffer(),
    };
  });

  if (entries.length === 0) {
    return {
      kind: "recordings",
      title: "No recordings",
      note: "None of the calls in this campaign have a recording yet.",
    };
  }

  await downloadZip(`campaign_${campaign.campaign_id}_recordings.zip`, entries);
  return {
    kind: "recordings",
    title: "Recordings downloaded",
    note: `${entries.length} of ${candidates.length} recordings in ZIP.`,
  };
}

export async function downloadCallRecording(callId: string): Promise<void> {
  const blob = await fetchCallRecordingBlob(callId);
  const type = blob.type?.trim() ? blob.type : "audio/wav";
  downloadBlob(await blob.arrayBuffer(), type, `${callId}.${audioExtension(blob.type)}`);
}

export async function downloadCallTranscript(callId: string): Promise<void> {
  const text = await fetchCallTranscriptText(callId);
  downloadBlob(text, "text/plain;charset=utf-8", `${callId}-transcript.txt`);
}
