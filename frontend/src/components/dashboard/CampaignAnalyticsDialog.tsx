"use client";

import { useMemo } from "react";
import { BarChart3, Download, FileAudio, FileText } from "lucide-react";
import { Button, IconButton } from "@/components/ui/Button";
import { StatCard } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Dialog, DialogHeader } from "@/components/ui/Dialog";
import { Select } from "@/components/ui/Select";
import { Input } from "@/components/ui/Field";
import { Spinner } from "@/components/ui/Spinner";
import { Tooltip } from "@/components/ui/Tooltip";
import { useCampaignAnalytics } from "@/hooks/useCampaignAnalytics";
import {
  dispositionBreakdown,
  dispositionFilterOptions,
  hasArtifactUrl,
  humanizeToken,
} from "@/lib/campaign-exports";
import { formatDateTime, formatDuration, maskPhoneNumber } from "@/lib/format";
import type { CampaignApiResponse, CampaignState } from "@/lib/api-types";

const DISPOSITION_OPTIONS = dispositionFilterOptions();

function stateTone(state: CampaignState) {
  if (state === "running") return "live" as const;
  if (state === "completed" || state === "syncing") return "accent" as const;
  if (state === "failed") return "danger" as const;
  return "neutral" as const;
}

function progressPct(c: Pick<CampaignApiResponse, "total_rows" | "processed_rows">) {
  if (!c.total_rows) return 0;
  return (c.processed_rows / c.total_rows) * 100;
}

type Props = {
  open: boolean;
  initialCampaignId?: string | null;
  campaignOptions: CampaignApiResponse[];
  onClose: () => void;
  onNotify: (title: string, note: string) => void;
};

export function CampaignAnalyticsDialog({
  open,
  initialCampaignId,
  campaignOptions,
  onClose,
  onNotify,
}: Props) {
  const {
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
    pageSize,
    loadCampaign,
    downloadReport,
    downloadTranscriptsZip,
    downloadRecordingsZip,
    downloadRowRecording,
    downloadRowTranscript,
  } = useCampaignAnalytics(open, initialCampaignId, onNotify);

  const dispositionEntries = useMemo(
    () => dispositionBreakdown(analytics?.by_call_response),
    [analytics],
  );

  const progressPctValue =
    progress?.progress_percentage ?? (campaign ? progressPct(campaign) : 0);

  return (
    <Dialog open={open} onClose={onClose} widthClassName="max-w-4xl">
      <DialogHeader title="Campaign analytics" onClose={onClose} />
      <div className="flex flex-col gap-5 overflow-y-auto p-5">
        <div className="flex flex-col gap-3 rounded-v-md border border-v-line bg-v-soft/40 p-4">
          <span className="text-[13px] font-medium text-v-body">
            Enter a campaign ID to load analytics, calls, and downloads.
          </span>
          <div className="flex flex-wrap items-end gap-2">
            <label className="flex min-w-[16rem] flex-1 flex-col gap-1.5">
              <span className="font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">
                Campaign ID
              </span>
              <Input
                value={campaignIdInput}
                onChange={(e) => setCampaignIdInput(e.target.value)}
                placeholder="Campaign ID"
                onKeyDown={(e) => {
                  if (e.key === "Enter") void loadCampaign(campaignIdInput);
                }}
              />
            </label>
            {campaignOptions.length > 0 ? (
              <label className="flex min-w-[12rem] flex-col gap-1.5">
                <span className="font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">
                  Or pick one
                </span>
                <Select
                  size="sm"
                  aria-label="Pick campaign"
                  className="!h-10 !py-0"
                  value=""
                  onChange={(e) => {
                    const id = e.target.value;
                    if (!id) return;
                    setCampaignIdInput(id);
                    void loadCampaign(id);
                  }}
                >
                  <option value="">Select campaign…</option>
                  {campaignOptions.map((c) => (
                    <option key={c.campaign_id} value={c.campaign_id}>
                      {c.name}
                    </option>
                  ))}
                </Select>
              </label>
            ) : null}
            <Button
              variant="primary"
              size="sm"
              disabled={loading || !campaignIdInput.trim()}
              onClick={() => void loadCampaign(campaignIdInput)}
            >
              {loading ? <Spinner /> : <BarChart3 className="size-3.5" strokeWidth={1.75} />}
              Load analytics
            </Button>
          </div>
          {error ? <p className="text-sm text-v-danger">{error}</p> : null}
        </div>

        {loading ? (
          <div className="flex items-center gap-2 text-sm text-v-muted">
            <Spinner light={false} /> Loading analytics…
          </div>
        ) : null}

        {campaign && analytics ? (
          <>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="flex min-w-0 flex-col gap-1">
                <span className="truncate text-[17px] font-semibold tracking-tight">
                  {campaign.name}
                </span>
                <span className="font-mono text-[11px] text-v-muted">{campaign.campaign_id}</span>
                <Badge tone={stateTone(campaign.state)}>
                  {humanizeToken(campaign.state)}
                </Badge>
              </div>
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={exportBusy !== null}
                  onClick={() => void downloadReport()}
                >
                  {exportBusy === "report" ? (
                    <Spinner light={false} />
                  ) : (
                    <Download className="size-3.5" strokeWidth={1.75} />
                  )}
                  CSV report
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={exportBusy !== null}
                  onClick={() => void downloadTranscriptsZip()}
                >
                  {exportBusy === "transcripts" ? (
                    <Spinner light={false} />
                  ) : (
                    <FileText className="size-3.5" strokeWidth={1.75} />
                  )}
                  Transcripts ZIP
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={exportBusy !== null}
                  onClick={() => void downloadRecordingsZip()}
                >
                  {exportBusy === "recordings" ? (
                    <Spinner light={false} />
                  ) : (
                    <FileAudio className="size-3.5" strokeWidth={1.75} />
                  )}
                  Recordings ZIP
                </Button>
              </div>
            </div>

            <div className="flex flex-col gap-1.5">
              <span className="font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">
                Progress
              </span>
              <ProgressBar pct={progressPctValue} thick />
              <span className="text-[11px] text-v-muted">
                {(progress?.processed_rows ?? campaign.processed_rows).toLocaleString()} /{" "}
                {(progress?.total_rows ?? campaign.total_rows).toLocaleString()} placed
                {" · "}
                {(progress?.failed_rows ?? campaign.failed_rows).toLocaleString()} failed
              </span>
            </div>

            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatCard label="Attempted" value={String(analytics.calls_attempted)} />
              <StatCard label="Connected" value={String(analytics.calls_connected)} />
              <StatCard
                label="Connect rate"
                value={`${analytics.connection_rate.toFixed(1)}%`}
              />
              <StatCard
                label="Avg duration"
                value={formatDuration(analytics.average_duration_seconds)}
              />
            </div>

            {dispositionEntries.length > 0 ? (
              <div className="flex flex-col gap-2">
                <span className="font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">
                  Disposition breakdown
                </span>
                <div className="flex flex-col gap-2 rounded-v-md border border-v-line p-3">
                  {dispositionEntries.map((row) => (
                    <div key={row.key} className="flex items-center gap-3 text-sm">
                      <span className="w-24 shrink-0 text-v-body">
                        {humanizeToken(row.key)}
                      </span>
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-v-soft">
                        <div
                          className="h-full rounded-full bg-v-accent"
                          style={{ width: `${row.pct}%` }}
                        />
                      </div>
                      <span className="w-16 shrink-0 text-right font-mono text-[11px] text-v-muted">
                        {row.count} · {row.pct}%
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-v-line pt-4">
              <span className="text-[13px] font-medium text-v-body">Calls</span>
              <Select
                size="sm"
                aria-label="Filter by disposition"
                className="!h-9 !py-0"
                value={dispositionFilter}
                onChange={(e) => setDisposition(e.target.value)}
              >
                {DISPOSITION_OPTIONS.map((opt) => (
                  <option key={opt.value || "all"} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </Select>
            </div>

            {runsLoading ? (
              <div className="flex items-center gap-2 text-sm text-v-muted">
                <Spinner light={false} /> Loading calls…
              </div>
            ) : runs.length === 0 ? (
              <p className="text-sm text-v-muted">No calls match this filter.</p>
            ) : (
              <>
                <div className="overflow-x-auto rounded-v-md border border-v-line">
                  <table className="w-full min-w-[720px] border-collapse text-sm">
                    <thead>
                      <tr className="border-b border-v-line text-left font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">
                        <th className="px-4 py-3 font-medium">Number</th>
                        <th className="px-4 py-3 font-medium">Status</th>
                        <th className="px-4 py-3 font-medium">Response</th>
                        <th className="px-4 py-3 font-medium">Duration</th>
                        <th className="px-4 py-3 font-medium">When</th>
                        <th className="px-4 py-3 font-medium">Artifacts</th>
                      </tr>
                    </thead>
                    <tbody>
                      {runs.map((r, i) => {
                        const callId = r.call_id ? String(r.call_id) : "";
                        return (
                          <tr key={callId || i} className="border-b border-v-line last:border-b-0">
                            <td className="px-4 py-3 font-mono text-xs">
                              {maskPhoneNumber(r.to_number)}
                            </td>
                            <td className="px-4 py-3">{r.status ?? "–"}</td>
                            <td className="px-4 py-3">{r.call_response ?? "–"}</td>
                            <td className="px-4 py-3">{formatDuration(r.duration)}</td>
                            <td className="px-4 py-3 text-xs text-v-muted">
                              {formatDateTime(r.created_at)}
                            </td>
                            <td className="px-4 py-3">
                              <span className="flex items-center gap-1">
                                <Tooltip
                                  text={
                                    hasArtifactUrl(r.recording_url)
                                      ? "Download recording"
                                      : "No recording"
                                  }
                                >
                                  <IconButton
                                    aria-label="Download recording"
                                    disabled={
                                      !callId ||
                                      !hasArtifactUrl(r.recording_url) ||
                                      rowBusy !== null
                                    }
                                    onClick={() => callId && void downloadRowRecording(callId)}
                                    className="bg-v-soft hover:border-v-accent hover:bg-v-pale hover:text-v-accent disabled:opacity-40"
                                  >
                                    {rowBusy === `rec:${callId}` ? (
                                      <Spinner light={false} />
                                    ) : (
                                      <FileAudio className="size-3.5" strokeWidth={1.75} />
                                    )}
                                  </IconButton>
                                </Tooltip>
                                <Tooltip
                                  text={
                                    hasArtifactUrl(r.transcript_url)
                                      ? "Download transcript"
                                      : "No transcript"
                                  }
                                >
                                  <IconButton
                                    aria-label="Download transcript"
                                    disabled={
                                      !callId ||
                                      !hasArtifactUrl(r.transcript_url) ||
                                      rowBusy !== null
                                    }
                                    onClick={() => callId && void downloadRowTranscript(callId)}
                                    className="bg-v-soft hover:border-v-accent hover:bg-v-pale hover:text-v-accent disabled:opacity-40"
                                  >
                                    {rowBusy === `tr:${callId}` ? (
                                      <Spinner light={false} />
                                    ) : (
                                      <FileText className="size-3.5" strokeWidth={1.75} />
                                    )}
                                  </IconButton>
                                </Tooltip>
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {runsTotal > pageSize ? (
                  <div className="flex items-center justify-between gap-3 text-xs text-v-muted">
                    <span>
                      {runsOffset + 1}–{runsOffset + runs.length} of {runsTotal}
                    </span>
                    <div className="flex gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={runsOffset === 0}
                        onClick={() => setRunsOffset(Math.max(0, runsOffset - pageSize))}
                      >
                        Previous
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={runsOffset + runs.length >= runsTotal}
                        onClick={() => setRunsOffset(runsOffset + pageSize)}
                      >
                        Next
                      </Button>
                    </div>
                  </div>
                ) : null}
              </>
            )}
          </>
        ) : null}
      </div>
    </Dialog>
  );
}
