import { fetchCallRecordingBlob, fetchCallTranscriptText } from "@/lib/api/calls";
import {
  downloadCampaignReport,
  listAllCampaignRuns,
} from "@/lib/api/campaigns";
import type { CampaignApiResponse, CampaignRunItem } from "@/lib/api-types";
import {
  campaignExportBasename,
  defaultAudioContentType,
  recordingZipEntryPath,
  runsWithRecording,
  runsWithTranscript,
  singleRecordingFilename,
  singleTranscriptFilename,
  transcriptZipEntryPath,
} from "@/lib/campaign-artifacts";
import { downloadBlob } from "@/lib/report";
import { downloadZip } from "@/lib/zip";

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
  downloadBlob(blob, "text/csv", `${campaignExportBasename(campaign.campaign_id, "report")}.csv`);
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
  const candidates = runsWithTranscript(allRuns);
  const entries = await collectZipEntries(candidates, async (run) => {
    const callId = String(run.call_id);
    const text = await fetchCallTranscriptText(callId);
    return { path: transcriptZipEntryPath(callId), data: text };
  });

  if (entries.length === 0) {
    return {
      kind: "transcripts",
      title: "No transcripts",
      note: "None of the calls in this campaign have a transcript yet.",
    };
  }

  await downloadZip(
    `${campaignExportBasename(campaign.campaign_id, "transcripts")}.zip`,
    entries,
  );
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
  const candidates = runsWithRecording(allRuns);
  const entries = await collectZipEntries(candidates, async (run) => {
    const callId = String(run.call_id);
    const blob = await fetchCallRecordingBlob(callId);
    return {
      path: recordingZipEntryPath(callId, blob.type),
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

  await downloadZip(
    `${campaignExportBasename(campaign.campaign_id, "recordings")}.zip`,
    entries,
  );
  return {
    kind: "recordings",
    title: "Recordings downloaded",
    note: `${entries.length} of ${candidates.length} recordings in ZIP.`,
  };
}

export async function downloadCallRecording(callId: string): Promise<void> {
  const blob = await fetchCallRecordingBlob(callId);
  downloadBlob(
    await blob.arrayBuffer(),
    defaultAudioContentType(blob.type),
    singleRecordingFilename(callId, blob.type),
  );
}

export async function downloadCallTranscript(callId: string): Promise<void> {
  const text = await fetchCallTranscriptText(callId);
  downloadBlob(text, "text/plain;charset=utf-8", singleTranscriptFilename(callId));
}
