"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Brain, Download, Eye, Mic, Volume2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { Spinner } from "@/components/ui/Spinner";
import { CallTypeBadge } from "@/components/ui/CallTypeBadge";
import { InfoTip } from "@/components/ui/Tooltip";
import { CallDetailSheet } from "@/components/dashboard/CallDetailSheet";
import { useAuth } from "@/components/AuthProvider";
import { getAgent, listAgents } from "@/lib/api-client";
import { ApiError } from "@/lib/api/http";
import { getCall, getCallMetrics, listOrgCalls } from "@/lib/api/calls";
import { displayFromNumber, displayToNumber, formatDateTime, formatDuration, nameFromEmail } from "@/lib/format";
import { buildCsvReport, downloadBlob, type ReportMeta } from "@/lib/report";
import { formatMs, normalizeCallMetrics, type NormalizedCallMetrics } from "@/lib/call-metrics";
import type { AgentApiResponse, CallLogItem, CallType } from "@/lib/api-types";

const PAGE_SIZE = 10;

type TypeFilter = "all" | CallType;

const TYPE_FILTER_LABEL: Record<TypeFilter, string> = {
  all: "All types",
  inbound: "Inbound",
  outbound: "Outbound",
  web: "Web",
};

// SLA thresholds (ms) driving the KPI card color chips — tune per deployment.
const STT_WARN_MS = 800;
const STT_BAD_MS = 1500;
const LLM_TTFB_WARN_MS = 1500;
const LLM_TTFB_BAD_MS = 2500;
const TTS_WARN_MS = 500;
const TTS_BAD_MS = 1000;
const AVG_LATENCY_WARN_MS = 3000;
const AVG_LATENCY_BAD_MS = 5000;

type ThresholdTone = "good" | "warn" | "bad";

// Same status tokens Badge.tsx's live/warn/danger tones use, so a "Slow"
// chip here reads as the same semantic color as everywhere else in the app.
const THRESHOLD_STYLES: Record<ThresholdTone, string> = {
  good: "bg-v-ok-tint text-v-ok-ink border-v-ok-tint",
  warn: "bg-v-warn-tint text-v-warn-ink border-v-warn-tint",
  bad: "bg-v-danger-pale text-v-danger border-v-danger-line",
};
const THRESHOLD_LABELS: Record<ThresholdTone, string> = { good: "Good", warn: "Slow", bad: "Poor" };

function thresholdTone(value: number | undefined, warnAt: number, badAt: number): ThresholdTone | null {
  if (value === undefined) return null;
  if (value >= badAt) return "bad";
  if (value >= warnAt) return "warn";
  return "good";
}

// Chart palette pulled from the product's own design tokens (brand blue, ink,
// and warm neutral) instead of generic slate/gray hex, so the chart reads as
// part of the same system as every badge, button, and card on the page.
const STT_COLOR = "var(--v-accent)";
const LLM_COLOR = "var(--v-fg)";
const TTS_COLOR = "var(--v-faint)";
// Same danger token Badge.tsx / error banners use for the interrupted-turn marker.
const INTERRUPTED_MARK_COLOR = "var(--v-danger)";

/** Single source of truth for series order — the Bars render in this order, and
 * since recharts' <Legend> auto-derives its order from Bar render order, the
 * legend and the on-chart left-to-right bar order can never drift apart again. */
const LATENCY_SERIES: { key: "stt" | "llm" | "tts"; name: string; color: string }[] = [
  { key: "stt", name: "STT", color: STT_COLOR },
  { key: "llm", name: "LLM TTFB", color: LLM_COLOR },
  { key: "tts", name: "TTS 1st chunk", color: TTS_COLOR },
];

interface ChartTurnDatum {
  turn: string;
  turnNumber: number;
  interrupted: boolean;
  botInitiated: boolean;
  stt?: number;
  llm?: number;
  tts?: number;
}

interface BarShapeProps {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  payload?: ChartTurnDatum;
}

/** Draws a bar for one series, dashed-outlined when its turn was interrupted
 * (Von Restorff marker) and dimmed when a different turn is the active
 * chart/table selection. */
function makeBarShape(color: string, activeTurn: number | null) {
  return function BarShape(props: BarShapeProps) {
    const { x = 0, y = 0, width = 0, height = 0, payload } = props;
    if (width <= 0 || height <= 0) return <g />;
    const interrupted = Boolean(payload?.interrupted);
    const dimmed = activeTurn !== null && payload?.turnNumber !== activeTurn;
    return (
      <rect
        x={x}
        y={y}
        width={width}
        height={height}
        rx={2}
        fill={color}
        opacity={dimmed ? 0.35 : 1}
        stroke={interrupted ? INTERRUPTED_MARK_COLOR : "none"}
        strokeWidth={interrupted ? 1.5 : 0}
        strokeDasharray={interrupted ? "4 2" : undefined}
      />
    );
  };
}

/** recharts' per-Bar mouse handlers hand back either the flat datum or
 * {payload: datum} depending on the event — normalize both. */
function turnNumberFromBarEvent(data: unknown): number | undefined {
  const d = data as { turnNumber?: number; payload?: { turnNumber?: number } } | undefined;
  return d?.turnNumber ?? d?.payload?.turnNumber;
}

type MetricsState = NormalizedCallMetrics | "unavailable" | undefined;

const todayStamp = () => new Date().toISOString().slice(0, 10);

function EmptyCallsState({ subtitle }: { subtitle: string }) {
  return (
    <div className="flex flex-col items-center gap-1 rounded-v-md border border-dashed border-v-line bg-white p-12 text-center">
      <span className="text-sm font-semibold">No calls yet</span>
      <span className="text-xs font-light text-v-muted">{subtitle}</span>
    </div>
  );
}

function exportTurnsCsv(call: CallLogItem, metrics: NormalizedCallMetrics, meta: ReportMeta) {
  const header = ["Turn", "Duration (s)", "Interrupted", "STT (ms)", "LLM TTFB (ms)", "TTS 1st chunk (ms)"];
  const rows = metrics.turns
    .filter((t) => t.hasUserTurn)
    .map((t) => [t.turnNumber, t.durationSecs ?? "", t.wasInterrupted ? "yes" : "no", t.sttMs ?? "", t.llmTtfbMs ?? "", t.ttsMs ?? ""]);
  downloadBlob(
    buildCsvReport(meta, header, rows),
    "text/csv",
    `call-latency-${call.call_id}-${todayStamp()}.csv`,
  );
}

interface PreviousCallStats {
  avgSttMs?: number;
  avgLlmTtfbMs?: number;
  avgTtsMs?: number;
  roundTripAvgMs?: number;
}

function deltaFor(current: number | undefined, previous: number | undefined): number | undefined {
  if (current === undefined || previous === undefined) return undefined;
  return current - previous;
}

function StatCard({
  label,
  tip,
  icon: Icon,
  value,
  tone,
  deltaMs,
}: {
  label: string;
  tip: string;
  icon?: typeof Mic;
  value: string;
  tone: ThresholdTone | null;
  deltaMs?: number;
}) {
  return (
    <div className="flex flex-col gap-1.5 rounded-v-xl border border-v-line bg-v-panel p-3.5 shadow-[var(--v-shadow-card)]">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 font-mono text-[9.5px] uppercase tracking-[.14em] text-v-muted">
          {Icon ? <Icon className="size-3 shrink-0" strokeWidth={1.9} /> : null}
          {label}
          <InfoTip text={tip} />
        </span>
        {tone ? (
          <span className={`shrink-0 rounded-v-sm border px-1.5 py-0.5 text-[9px] font-semibold ${THRESHOLD_STYLES[tone]}`}>
            {THRESHOLD_LABELS[tone]}
          </span>
        ) : null}
      </div>
      <div className="flex items-baseline gap-2">
        <span className="text-xl font-semibold tabular-nums text-v-fg">{value}</span>
        {deltaMs !== undefined ? (
          <span
            className={`text-[11px] font-medium tabular-nums ${deltaMs <= 0 ? "text-v-ok-ink" : "text-v-danger"}`}
          >
            {deltaMs > 0 ? "+" : ""}
            {Math.round(deltaMs)}ms
          </span>
        ) : null}
      </div>
    </div>
  );
}

function modelLabel(config: Record<string, unknown> | undefined): string {
  if (!config) return "—";
  const { provider, model } = config as { provider?: string; model?: string };
  return [provider, model].filter(Boolean).join(" · ") || "—";
}

/** Everything about this specific call at a glance — who handled it, which
 * models it ran on, and which number was involved — so a user chasing a
 * latency spike doesn't have to jump to the agent or number pages to see
 * what they were even looking at. Model/number config comes from the agent
 * (GET /agents/{agent_id}), not the call log, since a call doesn't carry its
 * own copy of the agent's config. */
function CallOverviewPanel({ call, agent }: { call: CallLogItem; agent: AgentApiResponse | null }) {
  const isWeb = call.call_type === "web";
  const createdBy = agent?.created_by ? nameFromEmail(agent.created_by) : "—";

  const modelItems: { label: string; value: string; icon?: typeof Mic }[] = [
    { label: "STT model", value: modelLabel(agent?.config.models.stt_config), icon: Mic },
    { label: "TTS model", value: modelLabel(agent?.config.models.tts_config), icon: Volume2 },
    { label: "LLM model", value: modelLabel(agent?.config.models.llm_config), icon: Brain },
  ];

  // A web call is a browser test session with no real telephony numbers —
  // From/To/Provider/Linked number are all meaningless there (displayFrom/
  // ToNumber already just render "–" for it), so swap them for the one thing
  // that's actually true of a web call instead of padding the grid with dashes.
  const items: { label: string; value: string; icon?: typeof Mic }[] = [
    // First column: Channel, Outcome, Duration
    { label: "Channel", value: isWeb ? "Browser test call" : (call.telephony_provider ?? "—") },
    { label: "Outcome", value: call.call_response ?? call.status },
    { label: "Duration", value: formatDuration(call.duration) },

    // Second column: STT, LLM, TTS
    { label: "STT model", value: modelLabel(agent?.config.models.stt_config), icon: Mic },
    { label: "LLM model", value: modelLabel(agent?.config.models.llm_config), icon: Brain },
    { label: "TTS model", value: modelLabel(agent?.config.models.tts_config), icon: Volume2 },

    // Third column: Created by
    { label: "Created by", value: agent?.created_by ? nameFromEmail(agent.created_by) : "—" },
  ];

  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-v-xl border border-v-line bg-v-panel p-4 shadow-[var(--v-shadow-card)] sm:grid-cols-3">
      {items.map((item) => (
        <div key={item.label} className="flex min-w-0 flex-col gap-0.5">
          <span className="flex items-center gap-1.5 font-mono text-[9.5px] uppercase tracking-[.14em] text-v-muted">
            {item.icon ? <item.icon className="size-3" strokeWidth={1.9} /> : null}
            {item.label}
          </span>
          <span className="truncate text-[13px] font-medium text-v-fg" title={item.value}>
            {item.value}
          </span>
        </div>
      ))}
    </div>
  );
}

function CallMetricsDetail({
  call,
  state,
  previousStats,
  onNotify,
}: {
  call: CallLogItem;
  state: MetricsState;
  previousStats?: PreviousCallStats;
  onNotify: (title: string, note: string) => void;
}) {
  const { session } = useAuth();
  const [activeTurn, setActiveTurn] = useState<number | null>(null);
  const [detailsCall, setDetailsCall] = useState<CallLogItem | null>(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [agent, setAgent] = useState<AgentApiResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    setAgent(null);
    getAgent(call.agent_id)
      .then((res) => {
        if (!cancelled) setAgent(res);
      })
      .catch(() => {
        /* overview panel just falls back to "—" for agent/model fields */
      });
    return () => {
      cancelled = true;
    };
  }, [call.agent_id]);

  async function openDetails() {
    setDetailsLoading(true);
    try {
      const full = await getCall(call.call_id);
      setDetailsCall(full);
    } catch (err) {
      onNotify("Couldn't load call details", err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setDetailsLoading(false);
    }
  }

  const userTurns = state && state !== "unavailable" ? state.turns.filter((t) => t.hasUserTurn) : [];

  const header = (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex min-w-0 flex-col gap-1">
        <span className="font-medium text-v-fg">{call.agent_name ?? call.agent_id}</span>
      </div>
      <span className="flex items-center gap-2">
        <Button variant="ghost" size="sm" onClick={openDetails} disabled={detailsLoading}>
          {detailsLoading ? <Spinner light={false} /> : <Eye className="size-3.5" strokeWidth={1.75} />}
          View
        </Button>
        {state && state !== "unavailable" ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              exportTurnsCsv(call, state, {
                orgName: session?.orgName ?? session?.orgId ?? "—",
                email: session?.email ?? "—",
              })
            }
            disabled={userTurns.length === 0}
          >
            <Download className="size-3.5" strokeWidth={1.75} />
            Export CSV
          </Button>
        ) : null}
      </span>
    </div>
  );

  const detailSheet = detailsCall ? (
    <CallDetailSheet call={detailsCall} onClose={() => setDetailsCall(null)} showTelemetryLink={false} />
  ) : null;

  if (state === undefined) {
    return (
      <div className="flex flex-col gap-5 p-5">
        {header}
        {detailSheet}
        <CallOverviewPanel call={call} agent={agent} />
        <div className="flex items-center gap-2 p-6 text-sm text-v-muted">
          <Spinner light={false} /> Loading metrics…
        </div>
      </div>
    );
  }

  if (state === "unavailable") {
    return (
      <div className="flex flex-col gap-5 p-5">
        {header}
        {detailSheet}
        <CallOverviewPanel call={call} agent={agent} />
        <div className="flex flex-col items-center gap-2 rounded-v-xl border border-dashed border-v-line bg-v-panel p-12 text-center">
          <span className="text-sm font-semibold text-v-fg">No latency data</span>
          <span className="text-xs font-light text-v-muted">
            No latency data was recorded for this call yet.
          </span>
        </div>
      </div>
    );
  }

  const metrics = state;

  // All turns (including the bot-initiated one with no STT/LLM data) share one
  // axis so the chart never renders a phantom gap where a turn is missing.
  const chartData: ChartTurnDatum[] = metrics.turns.map((t) => ({
    turn: t.hasUserTurn ? `Turn ${t.turnNumber}` : `Turn ${t.turnNumber} · bot-initiated`,
    turnNumber: t.turnNumber,
    interrupted: Boolean(t.wasInterrupted),
    botInitiated: !t.hasUserTurn,
    stt: t.hasUserTurn ? (t.sttMs !== undefined ? Math.round(t.sttMs) : undefined) : undefined,
    llm: t.hasUserTurn ? (t.llmTtfbMs !== undefined ? Math.round(t.llmTtfbMs) : undefined) : undefined,
    tts: t.hasUserTurn ? (t.ttsMs !== undefined ? Math.round(t.ttsMs) : undefined) : undefined,
  }));

  return (
    <div className="flex flex-col gap-5 p-5">
      {header}
      {detailSheet}

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard
          label="Avg STT"
          tip="Average time to transcribe the caller's speech each turn."
          icon={Mic}
          value={formatMs(metrics.avgSttMs)}
          tone={thresholdTone(metrics.avgSttMs, STT_WARN_MS, STT_BAD_MS)}
          deltaMs={deltaFor(metrics.avgSttMs, previousStats?.avgSttMs)}
        />
        <StatCard
          label="Avg LLM TTFB"
          tip="Average time until the LLM returns its first token each turn."
          icon={Brain}
          value={formatMs(metrics.avgLlmTtfbMs)}
          tone={thresholdTone(metrics.avgLlmTtfbMs, LLM_TTFB_WARN_MS, LLM_TTFB_BAD_MS)}
          deltaMs={deltaFor(metrics.avgLlmTtfbMs, previousStats?.avgLlmTtfbMs)}
        />
        <StatCard
          label="Avg TTS 1st chunk"
          tip="Average time until the first audio chunk is ready each turn."
          icon={Volume2}
          value={formatMs(metrics.avgTtsMs)}
          tone={thresholdTone(metrics.avgTtsMs, TTS_WARN_MS, TTS_BAD_MS)}
          deltaMs={deltaFor(metrics.avgTtsMs, previousStats?.avgTtsMs)}
        />
        <StatCard
          label="Avg Latency"
          tip="Average total STT + LLM + TTS pipeline time per turn."
          value={formatMs(metrics.avgLatencyMs)}
          tone={thresholdTone(metrics.avgLatencyMs, AVG_LATENCY_WARN_MS, AVG_LATENCY_BAD_MS)}
        />
      </div>

      <CallOverviewPanel call={call} agent={agent} />

      
      {/* Chart and table are one merged view of the same per-turn dataset —
          hovering/clicking either half highlights the same turn in both. */}
      <div className="overflow-hidden rounded-v-xl border border-v-line bg-v-panel shadow-[var(--v-shadow-card)]">
        <div className="border-b border-v-line px-4 py-3">
          <h3 className="font-mono text-[10px] uppercase tracking-[.16em] text-v-muted">Latency by turn</h3>
          
        </div>

        {chartData.length > 0 ? (
          <div className="h-56 border-b border-v-line p-4">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={chartData}
                barCategoryGap="20%"
                margin={{ top: 4, right: 8, left: 0, bottom: 4 }}
                onMouseLeave={() => setActiveTurn(null)}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="var(--v-line)" />
                <XAxis
                  dataKey="turn"
                  tick={{ fontSize: 11, fill: "var(--v-muted)" }}
                  stroke="var(--v-line)"
                  interval={0}
                />
                <YAxis tick={{ fontSize: 11, fill: "var(--v-muted)" }} stroke="var(--v-line)" unit="ms" />
                <Tooltip
                  cursor={{ fill: "var(--v-soft)" }}
                  contentStyle={{
                    borderRadius: 9,
                    border: "1px solid var(--v-line)",
                    background: "var(--v-panel)",
                    boxShadow: "var(--v-shadow-card)",
                    fontSize: 12,
                  }}
                  labelStyle={{ color: "var(--v-fg)", fontWeight: 600, marginBottom: 4 }}
                />
                <Legend wrapperStyle={{ fontSize: 11.5, color: "var(--v-muted-2)" }} iconType="circle" iconSize={8} />
                {LATENCY_SERIES.map((series) => (
                  <Bar
                    key={series.key}
                    dataKey={series.key}
                    name={series.name}
                    shape={makeBarShape(series.color, activeTurn)}
                    onMouseEnter={(data: unknown) => {
                      const n = turnNumberFromBarEvent(data);
                      if (n !== undefined) setActiveTurn(n);
                    }}
                    onClick={(data: unknown) => {
                      const n = turnNumberFromBarEvent(data);
                      if (n !== undefined) setActiveTurn(n);
                    }}
                  />
                ))}
              </BarChart>
            </ResponsiveContainer>
          </div>
        ) : null}

        {chartData.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm font-light text-v-muted">
            No turn data recorded for this call.
          </p>
        ) : (
          <div className="max-h-[min(400px,50vh)] w-full max-w-full overflow-auto">
            <table className="w-full min-w-[560px] text-left text-[13px]">
              <thead className="sticky top-0 bg-v-surface-sunk font-mono text-[10.5px] uppercase tracking-[.08em] text-v-dim">
                <tr>
                  <th className="px-4 py-2 font-semibold">Turn</th>
                  <th className="px-4 py-2 font-semibold">Duration</th>
                  <th className="px-4 py-2 font-semibold">STT</th>
                  <th className="px-4 py-2 font-semibold">LLM TTFB</th>
                  <th className="px-4 py-2 font-semibold">TTS 1st chunk</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-v-line">
                {metrics.turns.map((t) => {
                  const active = t.turnNumber === activeTurn;
                  return (
                    <tr
                      key={t.turnNumber}
                      onMouseEnter={() => setActiveTurn(t.turnNumber)}
                      onMouseLeave={() => setActiveTurn(null)}
                      onClick={() => setActiveTurn(t.turnNumber)}
                      className={`cursor-pointer transition-colors duration-[120ms] ${
                        active ? "bg-v-soft" : t.wasInterrupted ? "bg-v-danger-pale" : undefined
                      }`}
                    >
                      <td className="px-4 py-2">
                        {t.hasUserTurn ? (
                          `Turn ${t.turnNumber}`
                        ) : (
                          <span className="italic text-v-muted">Turn {t.turnNumber} · bot-initiated</span>
                        )}
                        {t.wasInterrupted ? (
                          <span className="ml-1.5 text-[11px] text-v-danger">interrupted</span>
                        ) : null}
                      </td>
                      <td className="px-4 py-2 tabular-nums">
                        {t.durationSecs !== undefined ? `${t.durationSecs.toFixed(1)}s` : "—"}
                      </td>
                      <td className="px-4 py-2 tabular-nums">{t.hasUserTurn ? formatMs(t.sttMs) : "—"}</td>
                      <td className="px-4 py-2 tabular-nums">{t.hasUserTurn ? formatMs(t.llmTtfbMs) : "—"}</td>
                      <td className="px-4 py-2 tabular-nums">{t.hasUserTurn ? formatMs(t.ttsMs) : "—"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="border-t border-v-line px-4 py-2.5 text-[11px] font-light text-v-muted">
          Pipeline-internal timings only (STT/LLM/TTS service latency), recorded after each call ends.
        </p>
      </div>
    </div>
  );
}

export function Telemetry({
  onNotify,
  initialCallId,
}: {
  onNotify: (title: string, note: string) => void;
  /** Deep-link target (e.g. "Show telemetry" from the History call detail
   * sheet) — fetched directly and pinned as the selection regardless of
   * which page of the org's calls it falls on. */
  initialCallId?: string | null;
}) {
  const { session } = useAuth();
  const orgId = session?.orgId;

  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [calls, setCalls] = useState<CallLogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [metricsByCallId, setMetricsByCallId] = useState<Record<string, MetricsState>>({});
  const [selectedCallId, setSelectedCallId] = useState<string | null>(null);
  const [agents, setAgents] = useState<AgentApiResponse[]>([]);
  const [agentFilterId, setAgentFilterId] = useState("");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [dataOnly, setDataOnly] = useState(false);
  const [pinnedCall, setPinnedCall] = useState<CallLogItem | null>(null);
  const [pinnedState, setPinnedState] = useState<MetricsState>(undefined);
  const appliedInitialRef = useRef(false);

  const load = useCallback(
    async (nextOffset: number, opts: { preserveSelection?: boolean } = {}) => {
      if (!orgId) return;
      setLoading(true);
      setLoadError("");
      try {
        const res = await listOrgCalls(orgId, { limit: PAGE_SIZE, offset: nextOffset });
        setCalls(res.calls);
        setOffset(res.offset);
        setTotal(res.total);

        const entries: Record<string, MetricsState> = {};
        res.calls.forEach((c) => {
          entries[c.call_id] = undefined;
        });
        setMetricsByCallId((prev) => ({ ...prev, ...entries }));

        const results = await Promise.allSettled(res.calls.map((c) => getCallMetrics(c.call_id)));
        const resolved: Record<string, MetricsState> = {};
        let firstWithMetrics: string | null = null;
        results.forEach((result, i) => {
          const callId = res.calls[i]!.call_id;
          if (result.status === "fulfilled") {
            resolved[callId] = normalizeCallMetrics(result.value);
            if (!firstWithMetrics) firstWithMetrics = callId;
          } else {
            resolved[callId] = "unavailable";
          }
        });
        setMetricsByCallId((prev) => ({ ...prev, ...resolved }));
        if (!opts.preserveSelection) setSelectedCallId(firstWithMetrics);
      } catch (err) {
        const message = err instanceof Error ? err.message : "Could not load calls.";
        setLoadError(message);
        onNotify("Couldn't load calls", message);
      } finally {
        setLoading(false);
      }
    },
    [orgId, onNotify],
  );

  // Deep-link: fetch and pin the requested call directly (it may not be on
  // the first page of the org's calls), and skip the normal "first call with
  // metrics" auto-select just this once so it stays selected.
  useEffect(() => {
    if (!initialCallId || appliedInitialRef.current) return;
    appliedInitialRef.current = true;
    setSelectedCallId(initialCallId);
    getCall(initialCallId)
      .then((call) => {
        setPinnedCall(call);
        return getCallMetrics(initialCallId);
      })
      .then((metrics) => setPinnedState(normalizeCallMetrics(metrics)))
      .catch((err) => {
        setPinnedState("unavailable");
        if (!(err instanceof ApiError && err.status === 404)) {
          onNotify("Couldn't load that call", err instanceof Error ? err.message : "Something went wrong.");
        }
      });
  }, [initialCallId, onNotify]);

  useEffect(() => {
    load(0, { preserveSelection: Boolean(initialCallId) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [orgId]);

  useEffect(() => {
    let cancelled = false;
    listAgents()
      .then((res) => {
        if (!cancelled) setAgents(res);
      })
      .catch(() => {
        /* agent filter is a nice-to-have — page still works without it */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const canPrev = offset > 0;
  const canNext = offset + calls.length < total;

  // Filters apply within the currently loaded page, same as the History
  // page's filters — not a server-side query across the whole org.
  const filteredCalls = useMemo(() => {
    return calls.filter((c) => {
      if (agentFilterId && c.agent_id !== agentFilterId) return false;
      if (typeFilter !== "all" && c.call_type !== typeFilter) return false;
      if (dataOnly) {
        const state = metricsByCallId[c.call_id];
        if (!state || state === "unavailable") return false;
      }
      return true;
    });
  }, [calls, agentFilterId, typeFilter, dataOnly, metricsByCallId]);

  const selectedCall = useMemo(() => {
    if (pinnedCall && pinnedCall.call_id === selectedCallId) return pinnedCall;
    return calls.find((c) => c.call_id === selectedCallId) ?? null;
  }, [calls, selectedCallId, pinnedCall]);
  const selectedState =
    pinnedCall && pinnedCall.call_id === selectedCallId
      ? pinnedState
      : selectedCallId
        ? metricsByCallId[selectedCallId]
        : undefined;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1 border-b border-v-line pb-6">
        <h1 className="text-3xl font-semibold tracking-tight">Telemetry</h1>
        <p className="max-w-2xl text-sm font-light leading-relaxed text-v-muted">
          Per-turn STT, LLM, and TTS latency for completed calls.
        </p>
      </div>

      {loadError ? (
        <div className="rounded-v-md border border-v-danger-line bg-v-danger-pale px-4 py-3 text-sm text-v-danger">
          {loadError}
        </div>
      ) : null}

      {!loading && total === 0 ? (
        <EmptyCallsState subtitle="Complete a call to inspect per-turn latency here." />
      ) : (
        <>
      <div className="sticky top-0 z-30 flex flex-wrap items-center gap-2.5 rounded-v-md border border-v-line bg-white p-3.5 shadow-[var(--v-shadow-card)]">
        <div className="flex shrink-0 items-center gap-2">
          <span className="text-[13px] font-medium text-v-body">Agent</span>
          <Select
            size="sm"
            aria-label="Filter by agent"
            className="!h-9 !py-0"
            value={agentFilterId}
            onChange={(e) => setAgentFilterId(e.target.value)}
          >
            <option value="">All agents</option>
            {agents.map((a) => (
              <option key={a.agent_id} value={a.agent_id}>
                {a.name}
              </option>
            ))}
          </Select>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          <span className="text-[13px] font-medium text-v-body">Type</span>
          <Select
            size="sm"
            aria-label="Filter by call type"
            className="!h-9 !py-0"
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value as TypeFilter)}
          >
            {(Object.entries(TYPE_FILTER_LABEL) as [TypeFilter, string][]).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </div>

        <button
          type="button"
          onClick={() => setDataOnly((v) => !v)}
          className={`flex cursor-pointer items-center gap-1.5 rounded-v-lg border px-3.5 py-2 text-xs font-medium transition-colors duration-[120ms] ${
            dataOnly
              ? "border-v-fg bg-v-fg text-white"
              : "border-v-line bg-white text-v-muted-2 hover:border-v-accent"
          }`}
        >
          {dataOnly ? "With latency data" : "All calls"}
        </button>
      </div>

      <div className="flex flex-col gap-4 lg:flex-row lg:items-stretch">
        <div className="flex w-full min-h-0 flex-col overflow-hidden rounded-v-xl border border-v-line bg-v-panel shadow-[var(--v-shadow-card)] lg:w-[380px] lg:shrink-0">
          <div className="flex shrink-0 items-center gap-2 border-b border-v-line px-4 py-3">
            <span className="font-mono text-[10px] uppercase tracking-[.16em] text-v-muted">Calls</span>
            <span className="font-mono text-[10px] text-v-dim">
              {filteredCalls.length} of {calls.length}
            </span>
          </div>

          {loading ? (
            <div className="flex flex-1 items-center gap-2 px-4 py-6 text-sm text-v-muted">
              <Spinner light={false} /> Loading calls…
            </div>
          ) : filteredCalls.length === 0 ? (
            <div className="flex flex-1 items-center justify-center px-4 py-8 text-center text-sm font-light text-v-muted">
              {calls.length === 0 ? "No calls yet." : "Nothing matches these filters on this page."}
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col divide-y divide-v-line overflow-y-auto">
              {filteredCalls.map((call) => {
                const state = metricsByCallId[call.call_id];
                const selected = call.call_id === selectedCallId;
                const unavailable = state === "unavailable";
                return (
                  <button
                    key={call.call_id}
                    type="button"
                    onClick={() => setSelectedCallId(call.call_id)}
                    className={`flex shrink-0 cursor-pointer flex-col gap-1.5 px-4 py-3 text-left transition-colors duration-[120ms] ${
                      unavailable ? "opacity-50" : ""
                    } ${selected ? "bg-v-soft" : "hover:bg-v-surface-sunk"}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <CallTypeBadge type={call.call_type} />
                      {state === undefined ? (
                        <Spinner light={false} />
                      ) : unavailable ? (
                        <span className="text-[10px] font-medium text-v-muted">No latency data</span>
                      ) : null}
                    </div>
                    <span className="truncate text-[13px] font-medium text-v-fg">
                      {call.agent_name ?? call.agent_id}
                    </span>
                    <div className="flex items-center justify-between text-xs font-light text-v-muted">
                      <span>{formatDateTime(call.start_time_utc ?? call.created_at)}</span>
                      <span>{formatDuration(call.duration)}</span>
                    </div>
                  </button>
                );
              })}
            </div>
          )}

          {!loading && total > PAGE_SIZE ? (
            <div className="flex shrink-0 items-center justify-between gap-2 border-t border-v-line bg-v-bg px-4 py-3">
              <Button variant="ghost" size="sm" disabled={!canPrev} onClick={() => load(Math.max(0, offset - PAGE_SIZE))}>
                Previous
              </Button>
              <span className="font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">
                {offset + 1}–{offset + calls.length} of {total}
              </span>
              <Button variant="ghost" size="sm" disabled={!canNext} onClick={() => load(offset + PAGE_SIZE)}>
                Next
              </Button>
            </div>
          ) : null}
        </div>

        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-v-xl border border-v-line bg-v-panel shadow-[var(--v-shadow-card)]">
          {!selectedCall ? (
            <div className="flex flex-1 items-center justify-center p-12 text-center text-sm font-light text-v-muted">
              {calls.length === 0
                ? "No calls to show."
                : "Select a call on the left to see its latency breakdown."}
            </div>
          ) : (
            // Keyed on call_id so activeTurn (and any other local UI state)
            // resets by remounting instead of via an effect.
            <CallMetricsDetail
              key={selectedCall.call_id}
              call={selectedCall}
              state={selectedState}
              onNotify={onNotify}
            />
          )}
        </div>
      </div>
        </>
      )}
    </div>
  );
}
