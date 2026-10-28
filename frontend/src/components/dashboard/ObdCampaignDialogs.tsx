"use client";

import { useCallback, useEffect, useState } from "react";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { StatCard } from "@/components/ui/Card";
import { Dialog, DialogHeader } from "@/components/ui/Dialog";
import { Spinner } from "@/components/ui/Spinner";
import {
  downloadObdReport,
  getObdReport,
  getObdStatus,
} from "@/lib/api/campaigns";
import type {
  ObdCampaignStatus,
  ObdReportResponse,
} from "@/lib/api-types";
import { formatDuration } from "@/lib/format";
import { downloadBlob } from "@/lib/report";

type ReportProps = {
  campaignId: string | null;
  campaignName?: string;
  onClose: () => void;
};

export function ObdReportDialog({ campaignId, campaignName, onClose }: ReportProps) {
  const [report, setReport] = useState<ObdReportResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async (id: string) => {
    setLoading(true);
    setError("");
    try {
      setReport(await getObdReport(id));
    } catch (err) {
      setReport(null);
      setError(err instanceof Error ? err.message : "Couldn't load the provider report.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!campaignId) {
      setReport(null);
      setError("");
      return;
    }
    void load(campaignId);
  }, [campaignId, load]);

  async function downloadCsv() {
    if (!campaignId) return;
    setDownloading(true);
    setError("");
    try {
      const blob = await downloadObdReport(campaignId);
      downloadBlob(blob, "application/zip", `obd-report-${campaignId}.zip`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't download the report.");
    } finally {
      setDownloading(false);
    }
  }

  const summary = report?.summary;

  return (
    <Dialog open={campaignId !== null} onClose={onClose} widthClassName="max-w-5xl">
      <DialogHeader
        title={campaignName || "Campaign report"}
        subtitle="Call outcomes from the provider report"
        onClose={onClose}
      />
      <div className="flex flex-col gap-4 px-5 py-4">
        <div className="flex justify-end">
          <Button
            variant="outline"
            size="sm"
            disabled={!campaignId || downloading}
            onClick={() => void downloadCsv()}
          >
            {downloading ? <Spinner light={false} /> : <Download className="size-3.5" strokeWidth={1.75} />}
            Download report
          </Button>
        </div>
        {error ? <p className="text-sm text-v-danger">{error}</p> : null}
        {loading ? (
          <div className="flex items-center gap-2 text-sm text-v-muted">
            <Spinner light={false} /> Loading report…
          </div>
        ) : summary ? (
          <>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatCard label="Attempted" value={String(summary.attempted)} />
              <StatCard label="Connected" value={String(summary.connected)} />
              <StatCard label="Connect rate" value={`${summary.connection_rate.toFixed(1)}%`} />
              <StatCard
                label="Avg duration"
                value={formatDuration(summary.average_duration_seconds)}
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <StatCard label="Timeout" value={String(summary.timeout)} />
              <StatCard label="Line drop" value={String(summary.line_drop)} />
            </div>
            {report.rows.length === 0 ? (
              <p className="text-sm text-v-muted">No calls in this report.</p>
            ) : (
              <div className="overflow-x-auto rounded-v-md border border-v-line">
                <table className="w-full min-w-[720px] border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-v-line text-left font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">
                      <th className="px-4 py-3 font-medium">Number</th>
                      <th className="px-4 py-3 font-medium">Status</th>
                      <th className="px-4 py-3 font-medium">When</th>
                      <th className="px-4 py-3 font-medium">Duration</th>
                      <th className="px-4 py-3 font-medium">Recording</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.rows.map((row, index) => (
                      <tr key={`${row.provider_call_id ?? "row"}-${index}`} className="border-b border-v-line last:border-0">
                        <td className="px-4 py-3 font-mono text-[12px]">{row.phone || "–"}</td>
                        <td className="px-4 py-3">{row.dial_status || "–"}</td>
                        <td className="px-4 py-3 text-v-muted">{row.when || "–"}</td>
                        <td className="px-4 py-3">{formatDuration(row.duration_seconds)}</td>
                        <td className="px-4 py-3">
                          {row.recording_url ? (
                            <a
                              href={row.recording_url}
                              target="_blank"
                              rel="noreferrer"
                              className="text-v-accent underline"
                            >
                              Open
                            </a>
                          ) : (
                            <span className="text-v-muted">No recording</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        ) : null}
      </div>
    </Dialog>
  );
}

function statusValue(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "–";
  return String(value);
}

function StatusBlock({ status }: { status: ObdCampaignStatus }) {
  const counts: Array<[string, number | null | undefined]> = [
    ["Base received", status.total_base_received],
    ["Calls initiated", status.total_call_initiated],
    ["Connected", status.total_calls_connected],
    ["Not connected", status.total_calls_not_connected],
    ["Remaining in queue", status.remaining_in_queue],
  ];
  return (
    <div className="flex flex-col gap-3 rounded-v-md border border-v-line p-4">
      <div className="flex flex-col gap-1">
        <span className="text-[15px] font-semibold">{status.campaign_name || "Campaign"}</span>
        <span className="text-xs text-v-muted">{status.campaign_type || status.campaign_id}</span>
        <span className="text-sm font-medium">{status.current_status || "–"}</span>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {counts.map(([label, value]) => (
          <StatCard key={label} label={label} value={statusValue(value)} />
        ))}
        <StatCard
          label="Success rate"
          value={
            status.success_rate_percentage === null || status.success_rate_percentage === undefined
              ? "–"
              : `${status.success_rate_percentage}%`
          }
        />
      </div>
      <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs text-v-muted">Created</dt>
          <dd>{statusValue(status.created_time)}</dd>
        </div>
        <div>
          <dt className="text-xs text-v-muted">Window</dt>
          <dd>{statusValue(status.window)}</dd>
        </div>
        <div>
          <dt className="text-xs text-v-muted">End date</dt>
          <dd>{statusValue(status.end_date)}</dd>
        </div>
        <div>
          <dt className="text-xs text-v-muted">Retry</dt>
          <dd>
            {statusValue(status.retry_attempts)} attempts · {statusValue(status.retry_within)}{" "}
            {statusValue(status.retry_interval)}
          </dd>
        </div>
      </dl>
    </div>
  );
}

type StatusProps = {
  campaignId: string | null;
  campaignName?: string;
  onClose: () => void;
};

export function ObdStatusDialog({ campaignId, campaignName, onClose }: StatusProps) {
  const [statuses, setStatuses] = useState<ObdCampaignStatus[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async (id: string) => {
    setLoading(true);
    setError("");
    try {
      const res = await getObdStatus(id);
      setStatuses(res.statuses);
    } catch (err) {
      setStatuses([]);
      setError(err instanceof Error ? err.message : "Couldn't load campaign status.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!campaignId) {
      setStatuses([]);
      setError("");
      return;
    }
    void load(campaignId);
  }, [campaignId, load]);

  return (
    <Dialog open={campaignId !== null} onClose={onClose} widthClassName="max-w-3xl">
      <DialogHeader
        title="Status"
        subtitle={campaignName}
        onClose={onClose}
      />
      <div className="flex flex-col gap-4 px-5 py-4">
        <div className="flex justify-end">
          <Button
            variant="outline"
            size="sm"
            disabled={!campaignId || loading}
            onClick={() => campaignId && void load(campaignId)}
          >
            {loading ? <Spinner light={false} /> : null}
            Refresh
          </Button>
        </div>
        {error ? <p className="text-sm text-v-danger">{error}</p> : null}
        {loading && statuses.length === 0 ? (
          <div className="flex items-center gap-2 text-sm text-v-muted">
            <Spinner light={false} /> Loading status…
          </div>
        ) : null}
        {statuses.map((status) => (
          <StatusBlock key={status.campaign_id || status.campaign_name || "status"} status={status} />
        ))}
      </div>
    </Dialog>
  );
}
