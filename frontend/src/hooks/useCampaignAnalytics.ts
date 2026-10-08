"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  getCampaign,
  getCampaignAnalytics,
  getCampaignProgress,
  getCampaignRuns,
} from "@/lib/api/campaigns";
import type {
  CampaignAnalyticsResponse,
  CampaignApiResponse,
  CampaignProgressResponse,
  CampaignRunItem,
} from "@/lib/api-types";
import { CAMPAIGN_RUNS_PAGE_SIZE } from "@/lib/campaign-artifacts";
import {
  downloadCallRecording,
  downloadCallTranscript,
  exportCampaignRecordingsZip,
  exportCampaignReport,
  exportCampaignTranscriptsZip,
  type CampaignExportKind,
} from "@/lib/campaign-exports";

type NotifyFn = (title: string, note: string) => void;

export function useCampaignAnalytics(
  open: boolean,
  initialCampaignId: string | null | undefined,
  onNotify: NotifyFn,
) {
  const [campaignIdInput, setCampaignIdInput] = useState("");
  const [campaign, setCampaign] = useState<CampaignApiResponse | null>(null);
  const [analytics, setAnalytics] = useState<CampaignAnalyticsResponse | null>(null);
  const [progress, setProgress] = useState<CampaignProgressResponse | null>(null);
  const [runs, setRuns] = useState<CampaignRunItem[]>([]);
  const [runsTotal, setRunsTotal] = useState(0);
  const [runsOffset, setRunsOffset] = useState(0);
  const [dispositionFilter, setDispositionFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [runsLoading, setRunsLoading] = useState(false);
  const [error, setError] = useState("");
  const [exportBusy, setExportBusy] = useState<CampaignExportKind | null>(null);
  const [rowBusy, setRowBusy] = useState<string | null>(null);
  const autoLoadedId = useRef<string | null>(null);

  const resetResults = useCallback(() => {
    setCampaign(null);
    setAnalytics(null);
    setProgress(null);
    setRuns([]);
    setRunsTotal(0);
    setRunsOffset(0);
    setDispositionFilter("");
    setError("");
  }, []);

  useEffect(() => {
    if (!open) {
      autoLoadedId.current = null;
      setCampaignIdInput("");
      resetResults();
      setExportBusy(null);
      setRowBusy(null);
      return;
    }
    if (initialCampaignId) {
      setCampaignIdInput(initialCampaignId);
    }
  }, [open, initialCampaignId, resetResults]);

  const loadCampaign = useCallback(
    async (id: string) => {
      const campaignId = id.trim();
      if (!campaignId) {
        setError("Enter a campaign ID.");
        return;
      }
      setLoading(true);
      setError("");
      setDispositionFilter("");
      setRunsOffset(0);
      try {
        const [campaignRes, analyticsRes, progressRes] = await Promise.all([
          getCampaign(campaignId),
          getCampaignAnalytics(campaignId),
          getCampaignProgress(campaignId),
        ]);
        setCampaign(campaignRes);
        setAnalytics(analyticsRes);
        setProgress(progressRes);
      } catch (err) {
        resetResults();
        setError(err instanceof Error ? err.message : "Couldn't load campaign analytics.");
      } finally {
        setLoading(false);
      }
    },
    [resetResults],
  );

  useEffect(() => {
    if (!open || !initialCampaignId) return;
    if (autoLoadedId.current === initialCampaignId) return;
    autoLoadedId.current = initialCampaignId;
    void loadCampaign(initialCampaignId);
  }, [open, initialCampaignId, loadCampaign]);

  useEffect(() => {
    if (!campaign) return;
    let cancelled = false;
    setRunsLoading(true);
    getCampaignRuns(campaign.campaign_id, {
      limit: CAMPAIGN_RUNS_PAGE_SIZE,
      offset: runsOffset,
      call_response: dispositionFilter || undefined,
    })
      .then((res) => {
        if (cancelled) return;
        setRuns(res.calls);
        setRunsTotal(res.total);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Couldn't load calls.");
        }
      })
      .finally(() => {
        if (!cancelled) setRunsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [campaign, dispositionFilter, runsOffset]);

  function setDisposition(value: string) {
    setRunsOffset(0);
    setDispositionFilter(value);
  }

  async function runExport(
    kind: CampaignExportKind,
    action: (c: CampaignApiResponse) => Promise<{ title: string; note: string }>,
  ) {
    if (!campaign) return;
    setExportBusy(kind);
    try {
      const result = await action(campaign);
      onNotify(result.title, result.note);
    } catch (err) {
      onNotify("Download failed", err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setExportBusy(null);
    }
  }

  async function downloadReport() {
    await runExport("report", exportCampaignReport);
  }

  async function downloadTranscriptsZip() {
    await runExport("transcripts", exportCampaignTranscriptsZip);
  }

  async function downloadRecordingsZip() {
    await runExport("recordings", exportCampaignRecordingsZip);
  }

  async function downloadRowRecording(callId: string) {
    setRowBusy(`rec:${callId}`);
    try {
      await downloadCallRecording(callId);
    } catch (err) {
      onNotify("Download failed", err instanceof Error ? err.message : "Recording unavailable.");
    } finally {
      setRowBusy(null);
    }
  }

  async function downloadRowTranscript(callId: string) {
    setRowBusy(`tr:${callId}`);
    try {
      await downloadCallTranscript(callId);
    } catch (err) {
      onNotify("Download failed", err instanceof Error ? err.message : "Transcript unavailable.");
    } finally {
      setRowBusy(null);
    }
  }

  return {
    campaignIdInput,
    setCampaignIdInput,
    campaign,
    analytics,
    progress,
    runs,
    runsTotal,
    runsOffset,
    setRunsOffset,
    dispositionFilter,
    setDisposition,
    loading,
    runsLoading,
    error,
    exportBusy,
    rowBusy,
    pageSize: CAMPAIGN_RUNS_PAGE_SIZE,
    loadCampaign,
    downloadReport,
    downloadTranscriptsZip,
    downloadRecordingsZip,
    downloadRowRecording,
    downloadRowTranscript,
  };
}
