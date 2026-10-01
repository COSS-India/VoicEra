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
import { listAgents } from "@/lib/api-client";
import { listAllOrgCalls, listOrgCalls, fetchCallTranscriptText } from "@/lib/api/calls";
import { parseTranscript } from "@/lib/transcript";
import { displayFromNumber, displayToNumber, formatDuration } from "@/lib/format";
import { buildCsvReport, downloadBlob, type ReportMeta } from "@/lib/report";
import { CallDetailSheet } from "@/components/dashboard/CallDetailSheet";
import type { AgentApiResponse, CallLogItem, CallType } from "@/lib/api-types";

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

type DatePreset = "all" | "today" | "7d" | "30d" | "custom";

function isoDate(d: Date): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

/** Local midnight for a YYYY-MM-DD value — avoids the UTC shift from `new Date("YYYY-MM-DD")`. */
function startOfLocalDay(yyyyMmDd: string): number {
  const [y, m, d] = yyyyMmDd.split("-").map(Number);
  return new Date(y, m - 1, d, 0, 0, 0, 0).getTime();
}

/** Inclusive end of a local calendar day. */
function endOfLocalDay(yyyyMmDd: string): number {
  const [y, m, d] = yyyyMmDd.split("-").map(Number);
  return new Date(y, m - 1, d, 23, 59, 59, 999).getTime();
}

/** Maps a preset to a concrete from/to range; "custom" and "all" are handled by
 * the caller (custom keeps whatever's in the date inputs, all clears both). */
function presetToRange(preset: DatePreset): { from: string; to: string } {
  const today = isoDate(new Date());
  if (preset === "today") return { from: today, to: today };
  if (preset === "7d") {
    const from = new Date();
    from.setDate(from.getDate() - 6);
    return { from: isoDate(from), to: today };
  }
  if (preset === "30d") {
    const from = new Date();
    from.setDate(from.getDate() - 29);
    return { from: isoDate(from), to: today };
  }
  return { from: "", to: "" };
}

function callsToCsv(rows: CallLogItem[], meta: ReportMeta): string {
  const header = ["Call Type", "Agent", "To", "From", "Status", "Called On", "Duration (s)"];
  const dataRows = rows.map((r) => [
    r.call_type,
    r.agent_name ?? r.agent_id,
    r.to_number,
    r.from_number,
    r.status,
    r.start_time_utc ?? r.created_at ?? "",
    r.duration ?? "",
  ]);
  return buildCsvReport(meta, header, dataRows);
}

const todayStamp = () => new Date().toISOString().slice(0, 10);

interface ExportMenuProps {
  filteredCalls: CallLogItem[];
  orgId: string | undefined;
  meta: ReportMeta;
  selectedAgent: AgentApiResponse | null;
  onNotify: (title: string, note: string) => void;
  onPrint: () => void;
}

/** Hick's Law: four related-but-distinct actions grouped behind one disclosure
 * rather than four separate top-level buttons, so the toolbar stays scannable. */
function ExportMenu({ filteredCalls, orgId, meta, selectedAgent, onNotify, onPrint }: ExportMenuProps) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<"transcripts" | "agent" | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDocMouseDown(e: MouseEvent) {
      if (!menuRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [open]);

  function exportCsv() {
    downloadBlob(callsToCsv(filteredCalls, meta), "text/csv", `call-history-${todayStamp()}.csv`);
    setOpen(false);
  }

  function exportPdf() {
    setOpen(false);
    onPrint();
  }

  async function exportAllTranscripts() {
    if (!orgId) return;
    setBusy("transcripts");
    try {
      const allCalls = await listAllOrgCalls(orgId);
      const withTranscripts = allCalls.filter((c) => c.transcript_url);
      const header = ["Call ID", "Agent", "Call Type", "Called On", "Line Timestamp", "Role", "Content"];
      const rows: unknown[][] = [];
      let lineCount = 0;
      for (const call of withTranscripts) {
        try {
          const text = await fetchCallTranscriptText(call.call_id);
          for (const line of parseTranscript(text)) {
            rows.push([
              call.call_id,
              call.agent_name ?? call.agent_id,
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
      const allCalls = await listAllOrgCalls(orgId);
      const agentCalls = allCalls.filter((c) => c.agent_id === selectedAgent.agent_id);
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
      disabled: filteredCalls.length === 0,
      loading: false,
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
      hint: "Every call in this org, CSV",
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
  const [datePreset, setDatePreset] = useState<DatePreset>("all");
  /** Draft inputs — editing these alone never filters the table. */
  const [draftFrom, setDraftFrom] = useState("");
  const [draftTo, setDraftTo] = useState("");
  /** Applied range — only set by presets or the custom Apply button. */
  const [appliedFrom, setAppliedFrom] = useState("");
  const [appliedTo, setAppliedTo] = useState("");
  const [agents, setAgents] = useState<AgentApiResponse[]>([]);
  const [agentFilterId, setAgentFilterId] = useState(agentFromUrl);
  /** When any filter is active we page through the full org list client-side,
   * because the list endpoint has no filter params — otherwise a date range
   * only ever sees the current 20-row page and shows empty while total stays 870. */
  const [allCalls, setAllCalls] = useState<CallLogItem[] | null>(null);

  const hasDateFilter = Boolean(appliedFrom && appliedTo);
  const hasActiveFilters =
    hasDateFilter || typeFilter !== "all" || statusFilter !== "all" || Boolean(agentFilterId);
  const customDirty =
    datePreset === "custom" && (draftFrom !== appliedFrom || draftTo !== appliedTo);
  const canApplyCustom = Boolean(draftFrom && draftTo && draftFrom <= draftTo);

  function applyRange(from: string, to: string) {
    setAppliedFrom(from);
    setAppliedTo(to);
    setDraftFrom(from);
    setDraftTo(to);
    setOffset(0);
  }

  function onDatePresetChange(preset: DatePreset) {
    setDatePreset(preset);
    setOffset(0);
    if (preset === "custom") {
      // Show empty draft inputs; keep previous applied range until Apply.
      setDraftFrom(appliedFrom);
      setDraftTo(appliedTo);
      return;
    }
    if (preset === "all") {
      applyRange("", "");
      return;
    }
    const range = presetToRange(preset);
    applyRange(range.from, range.to);
  }

  function applyCustomRange() {
    if (!canApplyCustom) return;
    applyRange(draftFrom, draftTo);
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
        const res = await listOrgCalls(orgId, { limit: PAGE_SIZE, offset: nextOffset });
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
    [orgId],
  );

  const loadAllForFilters = useCallback(async () => {
    if (!orgId) return;
    setLoading(true);
    setLoadError("");
    try {
      const rows = await listAllOrgCalls(orgId);
      setAllCalls(rows);
      setLastUpdated(new Date());
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Couldn't load call history.");
      setAllCalls([]);
    } finally {
      setLoading(false);
    }
  }, [orgId]);

  useEffect(() => {
    if (!orgId) return;
    const id = orgId;
    let cancelled = false;

    async function run() {
      if (hasActiveFilters) {
        setLoading(true);
        setLoadError("");
        try {
          const rows = await listAllOrgCalls(id);
          if (cancelled) return;
          setAllCalls(rows);
          setLastUpdated(new Date());
        } catch (err) {
          if (cancelled) return;
          setLoadError(err instanceof Error ? err.message : "Couldn't load call history.");
          setAllCalls([]);
        } finally {
          if (!cancelled) setLoading(false);
        }
        return;
      }

      setAllCalls(null);
      setLoading(true);
      setLoadError("");
      try {
        const res = await listOrgCalls(id, { limit: PAGE_SIZE, offset: 0 });
        if (cancelled) return;
        setCalls(res.calls);
        setTotal(res.total);
        setOffset(res.offset);
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
  }, [orgId, hasActiveFilters]);

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const filteredAll = useMemo(() => {
    const source = hasActiveFilters ? (allCalls ?? []) : calls;
    const from = hasDateFilter ? startOfLocalDay(appliedFrom) : null;
    const to = hasDateFilter ? endOfLocalDay(appliedTo) : null;
    const rows = source.filter((c) => {
      if (typeFilter !== "all" && c.call_type !== typeFilter) return false;
      if (statusFilter !== "all" && c.status !== statusFilter) return false;
      if (agentFilterId && c.agent_id !== agentFilterId) return false;
      if (from === null || to === null) return true;
      const at = c.start_time_utc ?? c.created_at;
      const ts = at ? new Date(at).getTime() : null;
      if (ts === null || Number.isNaN(ts)) return false;
      return ts >= from && ts <= to;
    });
    // Stable newest-first so applying a range doesn't reshuffle ties.
    return rows.sort((a, b) => {
      const at = new Date(a.start_time_utc ?? a.created_at ?? 0).getTime();
      const bt = new Date(b.start_time_utc ?? b.created_at ?? 0).getTime();
      const diff = bt - at;
      return diff !== 0 ? diff : a.call_id.localeCompare(b.call_id);
    });
  }, [hasActiveFilters, allCalls, calls, typeFilter, statusFilter, agentFilterId, hasDateFilter, appliedFrom, appliedTo]);

  // Client-side page when filters are on; server page when they're off.
  const pageCalls = useMemo(() => {
    if (!hasActiveFilters) return filteredAll;
    return filteredAll.slice(offset, offset + PAGE_SIZE);
  }, [hasActiveFilters, filteredAll, offset]);

  const displayTotal = hasActiveFilters ? filteredAll.length : total;
  const canPrev = offset > 0;
  const canNext = offset + pageCalls.length < displayTotal;

  function refresh() {
    if (hasActiveFilters) {
      loadAllForFilters();
      return;
    }
    loadPage(offset);
  }

  function goPrev() {
    const next = Math.max(0, offset - PAGE_SIZE);
    if (hasActiveFilters) {
      setOffset(next);
      return;
    }
    loadPage(next);
  }

  function goNext() {
    const next = offset + PAGE_SIZE;
    if (hasActiveFilters) {
      setOffset(next);
      return;
    }
    loadPage(next);
  }

  const todayMax = isoDate(new Date());

  useEffect(() => {
    if (!hasActiveFilters) return;
    if (offset === 0) return;
    if (offset < filteredAll.length) return;
    setOffset(Math.max(0, Math.floor(Math.max(filteredAll.length - 1, 0) / PAGE_SIZE) * PAGE_SIZE));
  }, [hasActiveFilters, filteredAll.length, offset]);

  return (
    <>
    <div className="flex flex-col gap-6 print:hidden">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-v-line pb-6">
        <h1 className="text-3xl font-semibold tracking-tight">History</h1>
      </div>

      <div className="sticky top-0 z-30 flex flex-wrap items-center gap-x-6 gap-y-3 rounded-v-md border border-v-line bg-white p-3.5 shadow-[var(--v-shadow-card)]">
        <div className="flex shrink-0 items-center gap-2">
          <span className="text-[13px] font-medium text-v-body">Date</span>
          <Select
            size="sm"
            aria-label="Date range"
            className="!h-9 !py-0"
            value={datePreset}
            onChange={(e) => onDatePresetChange(e.target.value as DatePreset)}
          >
            <option value="all">All time</option>
            <option value="today">Today</option>
            <option value="7d">Last 7 days</option>
            <option value="30d">Last 30 days</option>
            <option value="custom">Custom range</option>
          </Select>
          {datePreset === "custom" ? (
            <>
              <input
                type="date"
                aria-label="From date"
                value={draftFrom}
                max={draftTo || todayMax}
                onChange={(e) => setDraftFrom(e.target.value)}
                className="h-9 rounded-v-lg border border-v-line-strong bg-white px-3.5 text-xs text-v-fg transition-colors duration-[120ms] hover:border-v-accent focus:border-v-accent focus:outline-none"
              />
              <span className="text-xs text-v-muted">to</span>
              <input
                type="date"
                aria-label="To date"
                value={draftTo}
                min={draftFrom || undefined}
                max={todayMax}
                onChange={(e) => setDraftTo(e.target.value)}
                className="h-9 rounded-v-lg border border-v-line-strong bg-white px-3.5 text-xs text-v-fg transition-colors duration-[120ms] hover:border-v-accent focus:border-v-accent focus:outline-none"
              />
              <Button
                size="sm"
                variant={customDirty ? "primary" : "outline"}
                disabled={!canApplyCustom || !customDirty}
                onClick={applyCustomRange}
              >
                Apply
              </Button>
            </>
          ) : null}
        </div>

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
            filteredCalls={filteredAll}
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

      {loading || (hasActiveFilters && allCalls === null) ? (
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
          <table className="w-full min-w-[900px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-v-line text-left font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">
                <th className="px-4 py-3 font-medium">Call Type</th>
                <th className="px-4 py-3 font-medium">Agent Name</th>
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

    <PrintableReport calls={filteredAll} meta={reportMeta} />
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
            {["Call Type", "Agent", "To", "From", "Status", "Called On", "Duration"].map((h) => (
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
