"use client";

import { useCallback, useEffect, useState } from "react";
import {
  BarChart,
  Bar,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import {
  BarChart3,
  Brain,
  Clock3,
  Download,
  List,
  Mic,
  Phone,
  PhoneCall,
  PhoneOff,
  Trophy,
  TrendingDown,
  TrendingUp,
  Users,
  Volume2,
  RefreshCw,
} from "lucide-react";
import { Card } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { useAuth } from "@/components/AuthProvider";
import { getOrgCallAnalytics } from "@/lib/api/calls";
import { formatDuration, formatHoursMinutes } from "@/lib/format";
import { createPdfReport, type ReportMeta } from "@/lib/report";
import type { CallAnalyticsResponse, ModelUsageEntry } from "@/lib/api-types";

const MODEL_BAR_COLORS = ["#7b9aff", "#7df8c5", "#ffcf8d"];


const AGENT_BAR_COLOR = "var(--v-accent)";

function updatedAtLabel(d: Date): string {
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function modelUsageLine(entry: ModelUsageEntry | null): string {
  if (!entry) return "—";
  const name = [entry.provider, entry.model].filter(Boolean).join(" · ") || "—";
  return `${name} (${entry.call_count.toLocaleString()} calls)`;
}

const PDF_ACCENT = "#2f6fed";
const PDF_OK = "#22c55e";
const PDF_DANGER = "#ef4444";

/** Builds an actual downloadable PDF from the analytics data, including real
 * bar-chart graphs for Agent Performance, Model Usage, and Connection
 * Breakdown — drawn as vector rectangles (via ReportMeta's barRow) rather
 * than rasterizing the on-screen recharts SVGs, which would either lose all
 * their CSS-custom-property colors or (for the icon-labeled Model Usage
 * chart) their foreignObject/Tailwind content once serialized standalone. */
function downloadAnalyticsPdf(data: CallAnalyticsResponse, meta: ReportMeta) {
  const report = createPdfReport("Analytics Report", meta);

  report.heading("Overview");
  report.row("Connection rate", `${data.connection_rate}%`);
  report.row("Calls attempted", data.calls_attempted.toLocaleString());
  report.row("Calls connected", data.calls_connected.toLocaleString());
  report.row("Calls failed", data.calls_failed.toLocaleString());
  report.row("Avg call duration", formatDuration(data.average_duration_seconds));
  report.row("Total minutes", Math.round(data.total_duration_seconds / 60).toLocaleString());
  if (data.trend_vs_last_week_pct !== null) {
    const trend = data.trend_vs_last_week_pct;
    report.row("Trend vs last week", `${trend >= 0 ? "+" : ""}${trend}%`);
  }

  report.heading("Agent Performance");
  if (data.agent_performance.length === 0) {
    report.paragraph("No calls yet.");
  } else {
    const maxCount = Math.max(...data.agent_performance.map((a) => a.call_count), 1);
    data.agent_performance.forEach((a, i) => {
      report.barRow(
        `${i + 1}. ${a.agent_name ?? "Unknown agent"}`,
        `${a.call_count.toLocaleString()} calls`,
        a.call_count / maxCount,
        PDF_ACCENT,
      );
    });
  }

  report.heading("Model Usage (by call volume)");
  const modelRows: { label: string; entry: ModelUsageEntry | null; color: string }[] = [
    { label: "STT", entry: data.model_usage.stt, color: MODEL_BAR_COLORS[0]! },
    { label: "TTS", entry: data.model_usage.tts, color: MODEL_BAR_COLORS[1]! },
    { label: "LLM", entry: data.model_usage.llm, color: MODEL_BAR_COLORS[2]! },
  ];
  const maxModelCount = Math.max(...modelRows.map((r) => r.entry?.call_count ?? 0), 1);
  modelRows.forEach((r) => {
    report.barRow(
      `${r.label} — ${modelUsageLine(r.entry)}`,
      "",
      (r.entry?.call_count ?? 0) / maxModelCount,
      r.color,
    );
  });

  report.heading("Connection Breakdown");
  const attempted = Math.max(1, data.calls_attempted);
  report.barRow("Connected", data.calls_connected.toLocaleString(), data.calls_connected / attempted, PDF_OK);
  report.barRow("Failed", data.calls_failed.toLocaleString(), data.calls_failed / attempted, PDF_DANGER);

  report.save(`analytics-${new Date().toISOString().slice(0, 10)}.pdf`);
}

function EmptyCallsState({ subtitle }: { subtitle: string }) {
  return (
    <div className="flex flex-col items-center gap-1 rounded-v-md border border-dashed border-v-line bg-white p-12 text-center">
      <span className="text-sm font-semibold">No calls yet</span>
      <span className="text-xs font-light text-v-muted">{subtitle}</span>
    </div>
  );
}

function StatTile({
  icon: Icon,
  label,
  value,
  note,
  noteAccent,
}: {
  icon: typeof Phone;
  label: string;
  value: string;
  note?: string;
  noteAccent?: boolean;
}) {
  return (
    <Card className="flex flex-col gap-3 p-4.5">
      <div className="flex items-center justify-between">
        <span className="text-[13px] font-medium text-v-body">{label}</span>
        <span className="flex size-8 items-center justify-center rounded-v-md bg-v-pale text-v-accent">
          <Icon className="size-4" strokeWidth={1.9} />
        </span>
      </div>
      <span className="text-[27px] font-semibold tracking-tight tabular-nums">{value}</span>
      {note ? (
        <span
          className={`flex items-center gap-1.5 text-xs font-light ${noteAccent ? "text-v-success" : "text-v-muted"}`}
        >
          {noteAccent ? <span className="size-1.5 rounded-full bg-v-success" /> : null}
          {note}
        </span>
      ) : null}
    </Card>
  );
}

function AgentPerformancePanel({ agents }: { agents: CallAnalyticsResponse["agent_performance"] }) {
  const [view, setView] = useState<"bar" | "list">("bar");
  const top = agents[0];
  const chartData = agents.map((a) => ({
    name: a.agent_name ?? "Unknown agent",
    count: a.call_count,
  }));

  return (
    <Card className="flex flex-col gap-4 p-4.5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <Users className="size-4.5 text-v-body" strokeWidth={1.9} />
          <div className="flex flex-col">
            <span className="text-sm font-semibold">Agent Performance</span>
            <span className="text-xs font-light text-v-muted">Call distribution by agent</span>
          </div>
        </div>
        <div className="flex items-center gap-1 rounded-v-md border border-v-line p-0.5">
          <button
            type="button"
            aria-label="Bar view"
            onClick={() => setView("bar")}
            className={`flex size-7 cursor-pointer items-center justify-center rounded-[6px] transition-colors duration-[120ms] ${
              view === "bar" ? "bg-v-fg text-white" : "text-v-muted hover:bg-v-soft"
            }`}
          >
            <BarChart3 className="size-3.5" strokeWidth={1.9} />
          </button>
          <button
            type="button"
            aria-label="List view"
            onClick={() => setView("list")}
            className={`flex size-7 cursor-pointer items-center justify-center rounded-[6px] transition-colors duration-[120ms] ${
              view === "list" ? "bg-v-fg text-white" : "text-v-muted hover:bg-v-soft"
            }`}
          >
            <List className="size-3.5" strokeWidth={1.9} />
          </button>
        </div>
      </div>

      {top ? (
        <div className="flex items-center justify-between gap-3 rounded-v-md bg-v-soft px-4 py-3">
          <div className="flex items-center gap-3">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-v-pale text-[13px] font-semibold text-v-accent">
              1
            </span>
            <div className="flex flex-col">
              <span className="text-[13px] font-semibold">{top.agent_name ?? "Unknown agent"}</span>
              <span className="text-xs font-light text-v-muted">Top performer</span>
            </div>
          </div>
          <span className="text-[13px] font-semibold tabular-nums">{top.call_count.toLocaleString()} calls</span>
        </div>
      ) : (
        <p className="text-sm font-light text-v-muted">No calls yet.</p>
      )}

      {agents.length === 0 ? null : view === "bar" ? (
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={chartData} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--v-line)" vertical={false} />
            <XAxis dataKey="name" tick={{ fontSize: 11, fill: "var(--v-muted)" }} tickLine={false} axisLine={false} />
            <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "var(--v-muted)" }} tickLine={false} axisLine={false} />
            <Tooltip contentStyle={{ borderRadius: 8, borderColor: "var(--v-line)", fontSize: 12.5 }} />
            <Bar dataKey="count" fill={AGENT_BAR_COLOR} radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      ) : (
        <div className="flex flex-col divide-y divide-v-hairline">
          {agents.map((a, i) => (
            <div key={`${a.agent_id ?? a.agent_name ?? "agent"}-${i}`} className="flex items-center justify-between py-2.5">
              <span className="flex items-center gap-2.5 text-[13px] font-medium">
                <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-v-soft text-xs font-semibold text-v-muted">
                  {i + 1}
                </span>
                {a.agent_name ?? "Unknown agent"}
              </span>
              <span className="text-[13px] font-light text-v-muted tabular-nums">{a.call_count.toLocaleString()} calls</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}


function ModelUsagePanel({ usage }: { usage: CallAnalyticsResponse["model_usage"] }) {
  const rows: { key: string; icon: typeof Mic; label: string; entry: ModelUsageEntry | null }[] = [
    { key: "stt", icon: Mic, label: "STT", entry: usage.stt },
    { key: "tts", icon: Volume2, label: "TTS", entry: usage.tts },
    { key: "llm", icon: Brain, label: "LLM", entry: usage.llm },
  ];
  const hasAny = rows.some((r) => r.entry);

  // Build bar chart data
  const chartData = rows.map(({ key, label, entry }) => ({
    key,
    label,
    icon: rows.find(r => r.label === label)?.icon || Mic,
    provider: entry?.provider ?? "",
    model: entry?.model ?? "",
    call_count: entry?.call_count ?? 0,
    entry,
  }));

  return (
    <Card className="flex flex-col gap-4 p-4.5">
      <div className="flex items-center gap-2.5">
        <BarChart3 className="size-4.5 text-v-body" strokeWidth={1.9} />
        <div className="flex flex-col">
          <span className="text-sm font-semibold">Model Usage</span>
          <span className="text-xs font-light text-v-muted">Most-used model per stage, by call volume</span>
        </div>
      </div>

      {!hasAny ? (
        <p className="text-sm font-light text-v-muted">No calls yet.</p>
      ) : (
        <ResponsiveContainer width="100%" height={180}>
          <BarChart
            data={chartData}
            margin={{ top: 12, right: 16, left: -20, bottom: 8 }}
            barCategoryGap={40}
            barGap={6}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="var(--v-line)" vertical={false} />
            <XAxis
              dataKey="label"
              tickLine={false}
              axisLine={false}
              tick={({ x, y, payload, index }) => {
                const Icon = rows[index]?.icon ?? Mic;
                return (
                  <g transform={`translate(${x},${Number(y) + 8})`}>
                    <foreignObject x={-14} y={-29} width={28} height={32}>
                      <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
                        <span className="flex size-7 items-center justify-center rounded-full bg-v-pale text-v-accent" style={{ marginBottom: 2 }}>
                          <Icon className="size-3.5" strokeWidth={1.9} />
                        </span>
                        <span className="text-[13px] font-medium text-v-muted">{payload.value}</span>
                      </div>
                    </foreignObject>
                  </g>
                );
              }}
            />
            <YAxis
              allowDecimals={false}
              tick={{ fontSize: 12, fill: "var(--v-muted)" }}
              axisLine={false}
              tickLine={false}
            />
            <Tooltip
              cursor={{ fill: "rgba(123, 154, 255, 0.08)" }}
              content={({ active, payload }) => {
                if (active && payload && payload.length && payload[0].payload.entry) {
                  const entry = payload[0].payload.entry as ModelUsageEntry;
                  return (
                    <div className="rounded-v-md border border-v-line bg-white px-3 py-2.5 text-xs shadow-lg">
                      <div className="mb-1 font-medium text-v-fg">
                        {entry.provider ? `${entry.provider} · ` : ""}
                        {entry.model}
                      </div>
                      <div className="text-v-muted">
                        {entry.call_count.toLocaleString()} calls
                      </div>
                    </div>
                  );
                }
                return (
                  <div className="rounded-v-md border border-v-line bg-white px-3 py-2.5 text-xs shadow-lg text-v-muted">
                    —
                  </div>
                );
              }}
            />
            <Bar dataKey="call_count" fill={MODEL_BAR_COLORS[0]} radius={[6, 6, 0, 0]}>
              {chartData.map((_, i) => (
                <Cell key={`cell-${i}`} fill={MODEL_BAR_COLORS[i] || MODEL_BAR_COLORS[0]} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      )}
    </Card>
  );
}

function ConnectionBreakdownPanel({ data }: { data: CallAnalyticsResponse }) {
  return (
    <Card className="flex flex-col gap-5 p-4.5">
      <div className="flex items-center gap-2.5">
        <Phone className="size-4.5 text-v-body" strokeWidth={1.9} />
        <span className="text-sm font-semibold">Connection Breakdown</span>
      </div>

      <div className="flex flex-col items-center gap-1 py-4">
        <span className="text-[44px] font-semibold tracking-tight tabular-nums">{data.connection_rate}%</span>
        <span className="text-sm font-light text-v-muted">of calls connected</span>
      </div>

      <div className="h-2 w-full overflow-hidden rounded-full bg-v-track">
        <div
          className="h-full rounded-full bg-v-accent-mid transition-[width] duration-300"
          style={{ width: `${Math.min(100, Math.max(0, data.connection_rate))}%` }}
        />
      </div>

      <div className="flex items-center justify-center gap-8 pt-1">
        <div className="flex flex-col items-center gap-0.5">
          <span className="text-xl font-semibold tabular-nums">{data.calls_connected.toLocaleString()}</span>
          <span className="text-xs font-light text-v-muted">connected</span>
        </div>
        <div className="h-9 w-px bg-v-line" />
        <div className="flex flex-col items-center gap-0.5">
          <span className="text-xl font-semibold tabular-nums">{data.calls_failed.toLocaleString()}</span>
          <span className="text-xs font-light text-v-muted">failed</span>
        </div>
      </div>
    </Card>
  );
}

export function Analytics({ onNotify }: { onNotify: (title: string, note: string) => void }) {
  const { session } = useAuth();
  const orgId = session?.orgId;

  const [data, setData] = useState<CallAnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);

  const load = useCallback(async () => {
    if (!orgId) return;
    setLoadError("");
    try {
      const res = await getOrgCallAnalytics(orgId);
      setData(res);
      setUpdatedAt(new Date());
    } catch (err) {
      const message = err instanceof Error ? err.message : "Couldn't load analytics.";
      setLoadError(message);
    } finally {
      setLoading(false);
    }
  }, [orgId]);

  useEffect(() => {
    load();
  }, [load]);

  const trend = data?.trend_vs_last_week_pct ?? null;
  const hasCalls = (data?.calls_attempted ?? 0) > 0;

  return (
    <div className="flex w-full flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-v-line pb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Analytics</h1>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={async () => {
              await load();
              onNotify("Refreshed", "Analytics are up to date.");
            }}
            className="flex min-w-[120px] items-center justify-center gap-1 rounded-v-md border border-v-line bg-white px-3.5 py-2 text-[13px] font-medium text-v-body transition-colors duration-[120ms] hover:bg-v-soft disabled:cursor-not-allowed disabled:opacity-45"
          >
            <RefreshCw className="size-4" strokeWidth={1.9} />
            Refresh
          </button>
          <button
            type="button"
            disabled={!data}
            onClick={() =>
              data &&
              downloadAnalyticsPdf(data, {
                orgName: session?.orgName ?? session?.orgId ?? "—",
                email: session?.email ?? "—",
              })
            }
            className="flex min-w-[120px] items-center justify-center gap-2 rounded-v-md border border-v-line bg-white px-3.5 py-2 text-[13px] font-medium text-v-body transition-colors duration-[120ms] hover:bg-v-soft disabled:cursor-not-allowed disabled:opacity-45"
          >
            <Download className="size-4" strokeWidth={1.9} />
            Download PDF
          </button>
        </div>
   
      </div>

      {loadError ? (
        <div className="rounded-v-md border border-v-danger-line bg-v-danger-pale px-4 py-3 text-sm text-v-danger">
          {loadError}
        </div>
      ) : null}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-v-muted">
          <Spinner light={false} /> Loading analytics…
        </div>
      ) : data ? (
        hasCalls ? (
        <>
          <div className="grid grid-cols-2 gap-3.5 lg:grid-cols-5">
            <StatTile icon={PhoneCall} label="Calls Attempted" value={data.calls_attempted.toLocaleString()} note="Total call attempts" />
            <StatTile
              icon={Phone}
              label="Calls Connected"
              value={data.calls_connected.toLocaleString()}
              note={`${data.connection_rate}% connected`}
              noteAccent
            />
            <StatTile icon={Clock3} label="Avg Call Duration" value={formatDuration(data.average_duration_seconds)} note="Per connected call" />
            <StatTile
              icon={PhoneOff}
              label="Total Minutes"
              value={Math.round(data.total_duration_seconds / 60).toLocaleString()}
              note="Minutes connected"
            />
            <StatTile
              icon={Trophy}
              label="Most Used Agent"
              value={data.agent_performance[0]?.agent_name ?? "—"}
              note={data.agent_performance[0] ? `${data.agent_performance[0].call_count.toLocaleString()} calls` : "No calls yet"}
            />
          </div>

          <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-3">
            <AgentPerformancePanel agents={data.agent_performance} />
            <ConnectionBreakdownPanel data={data} />
            <ModelUsagePanel usage={data.model_usage} />
          </div>
        </>
        ) : (
          <EmptyCallsState subtitle="Run your first agent call to see analytics here." />
        )
      ) : null}
    </div>
  );
}
