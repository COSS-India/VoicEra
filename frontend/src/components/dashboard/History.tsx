"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { ChevronDown, Download, Eye, FileText, RefreshCw, Table, User } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { CallTypeBadge, CALL_TYPE_META } from "@/components/ui/CallTypeBadge";
import { Select } from "@/components/ui/Select";
import { Spinner } from "@/components/ui/Spinner";
import { useAuth } from "@/components/AuthProvider";
import Link from "next/link";
import { listAgents } from "@/lib/api-client";
import { listAllOrgCalls, listOrgCalls, fetchCallTranscriptText } from "@/lib/api/calls";
import { listCampaigns } from "@/lib/api/campaigns";
import { parseTranscript } from "@/lib/transcript";
import { displayFromNumber, displayToNumber, formatDuration } from "@/lib/format";
import { buildCsvReport, downloadBlob, type ReportMeta } from "@/lib/report";
import { CallDetailSheet } from "@/components/dashboard/CallDetailSheet";
import { HistoryDateFilter } from "@/components/dashboard/HistoryDateFilter";
import type {
  AgentApiResponse,
  CallLogItem,
  CallType,
  CampaignApiResponse,
} from "@/lib/api-types";
import {
  buildHistoryListQuery,
  type CampaignScope,
  type DatePreset,
} from "@/lib/history-filters";
import { useDateRangeFilter } from "@/lib/use-date-range-filter";

const PAGE_SIZE = 20;

type TypeFilter = "all" | CallType;
type StatusFilter = "all" | "completed" | "failed" | "in_progress" | "ringing" | "initiated";

function relativeTime(from: Date, now: Date): string {
  const seconds = Math.max(0, Math.round((now.getTime() - from.getTime()) / 1000));
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return `${hours}h ago`;
}

function formatDateTime(iso?: string | null): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "–";
  return d.toLocaleString(undefined, {
    day: "2-digit",
    month: "2-digit",
    year: "2-digit",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

function statusTone(call: CallLogItem) {
  if (call.status === "failed" || call.call_response === "failed") return "danger" as const;
  if (call.status === "completed") return "live" as const;
  if (call.status === "in_progress" || call.status === "ringing") return "accent" as const;
  return "neutral" as const;
}

function callsToCsv(rows: CallLogItem[], meta: ReportMeta): string {
  const header = [
    "Call Type",
    "Agent",
    "Campaign",
    "To",
    "From",
    "Status",
    "Called On",
    "Duration (s)",
  ];
  const dataRows = rows.map((r) => [
    r.call_type,
    r.agent_name ?? r.agent_id,
    r.campaign_name ?? r.campaign_id ?? "",
    r.to_number,
    r.from_number,
    r.status,
    r.start_time_utc ?? r.created_at ?? "",
    r.duration ?? "",
  ]);
  return buildCsvReport(meta, header, dataRows);
}

function campaignScopeSelectValue(scope: CampaignScope): string {
  if (scope.mode === "all") return "all";
  if (scope.mode === "one_off") return "one_off";
  return `campaign:${scope.campaignId}`;
}

function parseCampaignScopeSelect(value: string): CampaignScope {
  if (value === "all") return { mode: "all" };
  if (value === "one_off") return { mode: "one_off" };
  if (value.startsWith("campaign:")) {
    return { mode: "campaign", campaignId: value.slice("campaign:".length) };
  }
  return { mode: "all" };
}

const todayStamp = () => new Date().toISOString().slice(0, 10);

interface ExportMenuProps {
  filteredCalls: CallLogItem[];
  listFilters: ReturnType<typeof buildHistoryListQuery>;
  orgId: string | undefined;
  meta: ReportMeta;
  selectedAgent: AgentApiResponse | null;
  onNotify: (title: string, note: string) => void;
  onPrint: () => void;
}

/** Hick's Law: four related-but-distinct actions grouped behind one disclosure
 * rather than four separate top-level buttons, so the toolbar stays scannable. */
function ExportMenu({
  filteredCalls,
  listFilters,
  orgId,
  meta,
  selectedAgent,
  onNotify,
  onPrint,
}: ExportMenuProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<"transcripts" | "agent" | "csv" | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDocMouseDown(e: MouseEvent) {
      if (!menuRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [open]);

  async function exportCsv() {
    if (!orgId) {
      downloadBlob(callsToCsv(filteredCalls, meta), "text/csv", `call-history-${todayStamp()}.csv`);
      setOpen(false);
      return;
    }
    setBusy("csv");
    try {
      const { limit: _l, offset: _o, ...filters } = listFilters;
      const rows = await listAllOrgCalls(orgId, filters);
      downloadBlob(callsToCsv(rows, meta), "text/csv", `call-history-${todayStamp()}.csv`);
      onNotify("Export complete", `${rows.length} calls exported.`);
    } catch (err) {
      onNotify("Export failed", err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(null);
      setOpen(false);
    }
  }

  function exportPdf() {
    setOpen(false);
    onPrint();
  }

  async function exportAllTranscripts() {
    if (!orgId) return;
    setBusy("transcripts");
    try {
      const { limit: _l, offset: _o, ...filters } = listFilters;
      const allCalls = await listAllOrgCalls(orgId, filters);
      const withTranscripts = allCalls.filter((c) => c.transcript_url);
      const header = ["Call ID", "Agent", "Campaign", "Call Type", "Called On", "Line Timestamp", "Role", "Content"];
      const rows: unknown[][] = [];
      let lineCount = 0;
      for (const call of withTranscripts) {
        try {
          const text = await fetchCallTranscriptText(call.call_id);
          for (const line of parseTranscript(text)) {
            rows.push([
              call.call_id,
              call.agent_name ?? call.agent_id,
              call.campaign_name ?? call.campaign_id ?? "",
              call.call_type,
              call.start_time_utc ?? call.created_at ?? "",
              line.timestamp,
              line.role,
              line.content,
            ]);
            lineCount += 1;
          }
        } catch {
          /* skip calls whose transcript failed to fetch — don't fail the whole export */
        }
      }
      downloadBlob(buildCsvReport(meta, header, rows), "text/csv", `all-transcripts-${todayStamp()}.csv`);
      onNotify("Export complete", `${lineCount} transcript lines from ${withTranscripts.length} calls.`);
    } catch (err) {
      onNotify("Export failed", err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(null);
      setOpen(false);
    }
  }

  async function exportForAgent() {
    if (!orgId || !selectedAgent) return;
    setBusy("agent");
    try {
      const agentCalls = await listAllOrgCalls(orgId, { agent_id: selectedAgent.agent_id });
      downloadBlob(
        callsToCsv(agentCalls, meta),
        "text/csv",
        `calls-${selectedAgent.name.replace(/\s+/g, "-").toLowerCase()}-${todayStamp()}.csv`,
      );
      onNotify("Export complete", `${agentCalls.length} calls for ${selectedAgent.name}.`);
    } catch (err) {
      onNotify("Export failed", err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(null);
      setOpen(false);
    }
  }

  const items = [
    {
      key: "csv",
      label: "Export as CSV",
      hint: "Current filtered view",
      icon: Table,
      onClick: exportCsv,
      disabled: filteredCalls.length === 0 && busy !== "csv",
      loading: busy === "csv",
    },
    {
      key: "pdf",
      label: "Export as PDF",
      hint: "Current filtered view",
      icon: FileText,
      onClick: exportPdf,
      disabled: filteredCalls.length === 0,
      loading: false,
    },
    {
      key: "transcripts",
      label: "Export all transcripts",
      hint: "Matching current filters, CSV",
      icon: Download,
      onClick: exportAllTranscripts,
      disabled: !orgId,
      loading: busy === "transcripts",
    },
    {
      key: "agent",
      label: "Export for selected agent",
      hint: selectedAgent ? `${selectedAgent.name}, CSV` : "Pick an agent in Filter first",
      icon: User,
      onClick: exportForAgent,
      disabled: !orgId || !selectedAgent,
      loading: busy === "agent",
    },
  ] as const;

  return (
    <div ref={menuRef} className="relative">
      <Button size="sm" onClick={() => setOpen((v) => !v)} disabled={busy !== null}>
        {busy ? <Spinner /> : <Download className="size-3.5" strokeWidth={1.75} />}
        Export
        <ChevronDown className="size-3.5" strokeWidth={1.75} />
      </Button>
      {open ? (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-2 w-64 overflow-hidden rounded-v-sm border border-v-line bg-white py-1.5 shadow-[0_8px_24px_rgba(11,11,12,0.12)]"
        >
          {items.map((item) => (
            <button
              key={item.key}
              type="button"
              role="menuitem"
              disabled={item.disabled || busy !== null}
              onClick={item.onClick}
              title={item.hint}
              className="flex w-full cursor-pointer items-start gap-2.5 px-3.5 py-2.5 text-left transition-colors hover:bg-v-soft disabled:cursor-not-allowed disabled:opacity-40"
            >
              {item.loading ? (
                <Spinner light={false} />
              ) : (
                <item.icon className="mt-0.5 size-3.5 shrink-0 text-v-muted" strokeWidth={1.75} />
              )}
              <span className="flex flex-col">
                <span className="text-[13px] font-medium text-v-fg">{item.label}</span>
                <span className="text-[11px] text-v-muted">{item.hint}</span>
              </span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function History({ onNotify }: { onNotify: (title: string, note: string) => void }) {
  const { session } = useAuth();
  const orgId = session?.orgId;
  const reportMeta: ReportMeta = {
    orgName: session?.orgName ?? session?.orgId ?? "—",
    email: session?.email ?? "—",
  };
  const [calls, setCalls] = useState<CallLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [now, setNow] = useState(() => new Date());
  const [selectedCall, setSelectedCall] = useState<CallLogItem | null>(null);
  const searchParams = useSearchParams();
  const agentFromUrl = searchParams.get("agent") ?? "";
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [campaignScope, setCampaignScope] = useState<CampaignScope>({ mode: "all" });
  const dateFilter = useDateRangeFilter();
  const [agents, setAgents] = useState<AgentApiResponse[]>([]);
  const [campaigns, setCampaigns] = useState<CampaignApiResponse[]>([]);
  const [agentFilterId, setAgentFilterId] = useState(agentFromUrl);
  const [exportCalls, setExportCalls] = useState<CallLogItem[]>([]);
  const [reloadToken, setReloadToken] = useState(0);

  const hasActiveFilters =
    dateFilter.hasDateFilter ||
    typeFilter !== "all" ||
    statusFilter !== "all" ||
    Boolean(agentFilterId) ||
    campaignScope.mode !== "all";

  const listFilters = useMemo(
    () =>
      buildHistoryListQuery({
        range: dateFilter.applied,
        type: typeFilter,
        status: statusFilter,
        agentId: agentFilterId,
        campaignScope,
      }),
    [dateFilter.applied, typeFilter, statusFilter, agentFilterId, campaignScope],
  );

  function onDatePresetChange(preset: DatePreset) {
    setOffset(0);
    const result = dateFilter.selectPreset(preset);
    if (result.shouldReload) setReloadToken((n) => n + 1);
  }

  function onApplyCustomRange() {
    const range = dateFilter.applyCustom();
    if (!range) return;
    setOffset(0);
    // Always reload on Apply (dograh pattern) so re-selecting dates is stable.
    setReloadToken((n) => n + 1);
  }

  useEffect(() => {
    let cancelled = false;
    listAgents()
      .then((res) => {
        if (!cancelled) setAgents(res);
      })
      .catch(() => {
        /* agent filter is a nice-to-have — table still works without it */
      });
    listCampaigns()
      .then((res) => {
        if (!cancelled) setCampaigns(res);
      })
      .catch(() => {
        /* campaign filter is optional */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedAgent = useMemo(
    () => agents.find((a) => a.agent_id === agentFilterId) ?? null,
    [agents, agentFilterId],
  );

  const loadPage = useCallback(
    async (nextOffset: number) => {
      if (!orgId) return;
      setLoading(true);
      setLoadError("");
      try {
        const res = await listOrgCalls(orgId, {
          ...listFilters,
          limit: PAGE_SIZE,
          offset: nextOffset,
        });
        setCalls(res.calls);
        setTotal(res.total);
        setOffset(res.offset);
        setLastUpdated(new Date());
      } catch (err) {
        setLoadError(err instanceof Error ? err.message : "Couldn't load call history.");
      } finally {
        setLoading(false);
      }
    },
    [orgId, listFilters],
  );

  useEffect(() => {
    if (!orgId) return;
    const id = orgId;
    let cancelled = false;

    async function run() {
      setLoading(true);
      setLoadError("");
      try {
        const res = await listOrgCalls(id, {
          ...listFilters,
          limit: PAGE_SIZE,
          offset: 0,
        });
        if (cancelled) return;
        setCalls(res.calls);
        setTotal(res.total);
        setOffset(0);
        setLastUpdated(new Date());
      } catch (err) {
        if (cancelled) return;
        setLoadError(err instanceof Error ? err.message : "Couldn't load call history.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void run();
    return () => {
      cancelled = true;
    };
  }, [orgId, listFilters, reloadToken]);

  // Keep a full filtered set for PDF print export.
  useEffect(() => {
    if (!orgId) {
      setExportCalls([]);
      return;
    }
    let cancelled = false;
    const { limit: _l, offset: _o, ...filters } = listFilters;
    listAllOrgCalls(orgId, filters)
      .then((rows) => {
        if (!cancelled) setExportCalls(rows);
      })
      .catch(() => {
        if (!cancelled) setExportCalls([]);
      });
    return () => {
      cancelled = true;
    };
  }, [orgId, listFilters, reloadToken]);

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const pageCalls = calls;
  const displayTotal = total;
  const canPrev = offset > 0;
  const canNext = offset + pageCalls.length < displayTotal;

  function refresh() {
    setReloadToken((n) => n + 1);
  }

  function goPrev() {
    loadPage(Math.max(0, offset - PAGE_SIZE));
  }

  function goNext() {
    loadPage(offset + PAGE_SIZE);
  }

  return (
    <>
    <div className="flex flex-col gap-6 print:hidden">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-v-line pb-6">
        <h1 className="text-3xl font-semibold tracking-tight">History</h1>
      </div>

      <div className="sticky top-0 z-30 flex flex-wrap items-center gap-x-6 gap-y-3 rounded-v-md border border-v-line bg-white p-3.5 shadow-[var(--v-shadow-card)]">
        <HistoryDateFilter
          preset={dateFilter.preset}
          draftFrom={dateFilter.draftFrom}
          draftTo={dateFilter.draftTo}
          canApply={dateFilter.canApply}
          onPresetChange={onDatePresetChange}
          onDraftFromChange={dateFilter.setDraftFrom}
          onDraftToChange={dateFilter.setDraftTo}
          onApply={onApplyCustomRange}
        />

        <div className="flex shrink-0 items-center gap-2">
          <span className="text-[13px] font-medium text-v-body">Call type</span>
          <Select
            size="sm"
            aria-label="Call type"
            className="!h-9 !py-0"
            value={typeFilter}
            onChange={(e) => {
              setOffset(0);
              setTypeFilter(e.target.value as TypeFilter);
            }}
          >
            <option value="all">All</option>
            <option value="inbound">Inbound</option>
            <option value="outbound">Outbound</option>
            <option value="web">Web</option>
          </Select>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <span className="text-[13px] font-medium text-v-body">Status</span>
          <Select
            size="sm"
            aria-label="Status"
            className="!h-9 !py-0"
            value={statusFilter}
            onChange={(e) => {
              setOffset(0);
              setStatusFilter(e.target.value as StatusFilter);
            }}
          >
            <option value="all">All</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
            <option value="in_progress">In progress</option>
            <option value="ringing">Ringing</option>
            <option value="initiated">Initiated</option>
          </Select>
        </div>

        {agents.length > 0 ? (
          <div className="flex shrink-0 items-center gap-2">
            <span className="text-[13px] font-medium text-v-body">Agent</span>
            <Select
              size="sm"
              aria-label="Filter by agent"
              className="!h-9 !py-0 min-w-[10rem] max-w-[14rem]"
              value={agentFilterId}
              onChange={(e) => {
                setOffset(0);
                setAgentFilterId(e.target.value);
              }}
            >
              <option value="">All agents</option>
              {agents.map((a) => (
                <option key={a.agent_id} value={a.agent_id}>
                  {a.name}
                </option>
              ))}
            </Select>
          </div>
        ) : null}

        <div className="flex shrink-0 items-center gap-2">
          <span className="text-[13px] font-medium text-v-body">Campaign</span>
          <Select
            size="sm"
            aria-label="Filter by campaign"
            className="!h-9 !py-0 min-w-[11rem] max-w-[16rem]"
            value={campaignScopeSelectValue(campaignScope)}
            onChange={(e) => {
              setOffset(0);
              setCampaignScope(parseCampaignScopeSelect(e.target.value));
            }}
          >
            <option value="all">All calls</option>
            <option value="one_off">One-off only</option>
            {campaigns.map((c) => (
              <option key={c.campaign_id} value={`campaign:${c.campaign_id}`}>
                {c.name}
              </option>
            ))}
          </Select>
        </div>

        <span className="ml-auto flex shrink-0 items-center gap-2.5">
          <span className="font-mono text-[10px] uppercase tracking-[.12em] text-v-muted">
            {lastUpdated ? `Updated ${relativeTime(lastUpdated, now)}` : ""}
          </span>
          <button
            type="button"
            aria-label="Refresh"
            onClick={refresh}
            className="flex size-9 cursor-pointer items-center justify-center rounded-full border border-v-line bg-white text-v-muted transition-colors hover:border-v-accent hover:text-v-accent"
          >
            <RefreshCw className="size-3.5" strokeWidth={2} />
          </button>
          <ExportMenu
            filteredCalls={pageCalls}
            listFilters={listFilters}
            orgId={orgId}
            meta={reportMeta}
            selectedAgent={selectedAgent}
            onNotify={onNotify}
            onPrint={() => window.print()}
          />
        </span>
      </div>

      {loadError ? (
        <div className="rounded-v-md border border-v-danger-line bg-v-danger-pale px-4 py-3 text-sm text-v-danger">
          {loadError}
        </div>
      ) : null}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-v-muted">
          <Spinner light={false} /> Loading calls…
        </div>
      ) : pageCalls.length === 0 ? (
        <div className="flex flex-col items-center gap-1 rounded-v-md border border-dashed border-v-line bg-white p-12 text-center">
          <span className="text-sm font-semibold">
            {hasActiveFilters ? "No matching calls" : "No calls yet"}
          </span>
          <span className="text-xs font-light text-v-muted">
            {hasActiveFilters
              ? "Try a wider date range or clear filters to see more calls."
              : "Telephony calls and test calls will show up here once they happen."}
          </span>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-v-md border border-v-line bg-white">
          <table className="w-full min-w-[980px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-v-line text-left font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">
                <th className="px-4 py-3 font-medium">Call Type</th>
                <th className="px-4 py-3 font-medium">Agent Name</th>
                <th className="px-4 py-3 font-medium">Campaign</th>
                <th className="px-4 py-3 font-medium">To</th>
                <th className="px-4 py-3 font-medium">From</th>
                <th className="px-4 py-3 font-medium">Call Status</th>
                <th className="px-4 py-3 font-medium">Called On</th>
                <th className="px-4 py-3 font-medium">Duration</th>
                <th className="px-4 py-3 font-medium">Conversation Data</th>
              </tr>
            </thead>
            <tbody>
              {pageCalls.map((c) => {
                return (
                  <tr key={c.call_id} className="border-b border-v-line last:border-b-0">
                    <td className="px-4 py-3">
                      <CallTypeBadge type={c.call_type} />
                    </td>
                    <td className="px-4 py-3 font-medium">{c.agent_name ?? c.agent_id}</td>
                    <td className="px-4 py-3 text-v-muted">
                      {c.campaign_id ? (
                        <Link
                          href={`/batches?campaign=${encodeURIComponent(c.campaign_id)}`}
                          className="text-v-accent hover:underline"
                        >
                          {c.campaign_name ?? c.campaign_id}
                        </Link>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-v-muted">{displayToNumber(c)}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-v-muted">{displayFromNumber(c)}</td>
                    <td className="px-4 py-3">
                      <Badge tone={statusTone(c)}>{c.status.replace("_", " ")}</Badge>
                    </td>
                    <td className="px-4 py-3 text-v-muted">{formatDateTime(c.start_time_utc ?? c.created_at)}</td>
                    <td className="px-4 py-3 text-v-muted">{formatDuration(c.duration)}</td>
                    <td className="px-4 py-3">
                      <Button variant="outline" size="sm" onClick={() => setSelectedCall(c)}>
                        <Eye className="size-3.5" strokeWidth={1.9} />
                        View
                      </Button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {!loading && displayTotal > PAGE_SIZE ? (
        <div className="flex items-center justify-between gap-3 text-xs text-v-muted">
          <span>
            {offset + 1}–{offset + pageCalls.length} of {displayTotal}
          </span>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" disabled={!canPrev} onClick={goPrev}>
              Previous
            </Button>
            <Button variant="ghost" size="sm" disabled={!canNext} onClick={goNext}>
              Next
            </Button>
          </div>
        </div>
      ) : null}

      {selectedCall ? (
        <CallDetailSheet call={selectedCall} onClose={() => setSelectedCall(null)} />
      ) : null}
    </div>

    <PrintableReport calls={exportCalls} meta={reportMeta} />
    </>
  );
}

/** Print-only view for "Export as PDF" — window.print() lets the browser's own
 * print dialog save to PDF, so no PDF library is needed. Hidden on screen,
 * shown only in the print media query; the interactive view above is the
 * inverse (print:hidden), so exactly one of the two renders on paper. */
function PrintableReport({ calls, meta }: { calls: CallLogItem[]; meta: ReportMeta }) {
  return (
    <div className="print-area hidden print:block">
      <h1 className="mb-1 text-xl font-semibold">Call History</h1>
      <p className="mb-4 text-xs text-v-muted">
        Generated {new Date().toLocaleString()} · {calls.length} calls
      </p>
      <table className="w-full border-collapse text-xs">
        <thead>
          <tr>
            {["Call Type", "Agent", "Campaign", "To", "From", "Status", "Called On", "Duration"].map((h) => (
              <th key={h} className="border border-v-line px-2 py-1.5 text-left">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {calls.map((c) => (
            <tr key={c.call_id}>
              <td className="border border-v-line px-2 py-1.5">{CALL_TYPE_META[c.call_type].label}</td>
              <td className="border border-v-line px-2 py-1.5">{c.agent_name ?? c.agent_id}</td>
              <td className="border border-v-line px-2 py-1.5">{c.campaign_name ?? c.campaign_id ?? "—"}</td>
              <td className="whitespace-nowrap border border-v-line px-2 py-1.5">{displayToNumber(c)}</td>
              <td className="whitespace-nowrap border border-v-line px-2 py-1.5">{displayFromNumber(c)}</td>
              <td className="border border-v-line px-2 py-1.5">{c.status}</td>
              <td className="border border-v-line px-2 py-1.5">{formatDateTime(c.start_time_utc ?? c.created_at)}</td>
              <td className="border border-v-line px-2 py-1.5">{formatDuration(c.duration)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-4 border-t border-v-line pt-2 text-[10px] text-v-muted">
        {meta.orgName} · Downloaded by {meta.email}
      </p>
    </div>
  );
}
