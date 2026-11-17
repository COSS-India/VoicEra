"use client";

import { useMemo } from "react";
import { Card } from "@/components/ui/Card";
import {
  formatSlaActual,
  formatSlaTarget,
  metricDotClass,
  metricRowHighlighted,
} from "@/lib/sla-format";
import {
  buildPerformanceMetrics,
  countMissedTargets,
  groupPerformanceSections,
} from "@/lib/sla-metrics";
import type {
  SlaMetric,
  SlaMetricsPayload,
  SlaTelemetryResponse,
} from "@/lib/sla-types";

function MetricRow({ metric }: { metric: SlaMetric }) {
  const highlighted = metricRowHighlighted(metric.status);
  return (
    <div
      className={`grid grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)] items-center gap-3 rounded-v-sm px-3 py-2.5 ${
        highlighted ? "bg-v-danger-pale/40" : ""
      }`}
    >
      <div className="flex min-w-0 items-center gap-2.5">
        <span
          className={`size-2 shrink-0 rounded-full ${metricDotClass(metric.status)}`}
          aria-hidden
        />
        <div className="min-w-0 flex flex-col gap-0.5">
          <span className="truncate text-sm font-medium text-v-fg">{metric.label}</span>
          {metric.scope === "deployment" ? (
            <span className="font-mono text-[9px] uppercase tracking-[.1em] text-v-muted">
              Deployment
            </span>
          ) : (
            <span className="font-mono text-[9px] uppercase tracking-[.1em] text-v-muted">
              Campaign
            </span>
          )}
        </div>
      </div>
      <span className="text-sm text-v-muted">{formatSlaTarget(metric)}</span>
      <span
        className={`text-sm font-medium tabular-nums ${
          highlighted ? "text-v-danger" : "text-v-fg"
        }`}
      >
        {formatSlaActual(metric)}
      </span>
    </div>
  );
}

type Props = {
  telemetry: SlaTelemetryResponse | null;
  gpu: SlaMetricsPayload | null;
  telephony: SlaMetricsPayload | null;
  availability: SlaMetricsPayload | null;
};

export function SlaPerformanceTab({
  telemetry,
  gpu,
  telephony,
  availability,
}: Props) {
  const metrics = useMemo(
    () => buildPerformanceMetrics(telemetry, gpu, telephony, availability),
    [telemetry, gpu, telephony, availability],
  );
  const sections = useMemo(() => groupPerformanceSections(metrics), [metrics]);
  const { missed, total } = useMemo(() => countMissedTargets(metrics), [metrics]);

  if (total === 0) {
    return (
      <div className="flex flex-col items-center gap-1 rounded-v-md border border-dashed border-v-line bg-white p-12 text-center">
        <span className="text-sm font-semibold">No performance metrics yet</span>
        <span className="text-xs font-light text-v-muted">
          Load a campaign to see agreed targets versus actuals.
        </span>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <Card
        className={`flex flex-col gap-1 p-5 ${
          missed > 0 ? "border-v-danger-line bg-v-danger-pale/40" : "bg-v-soft/50"
        }`}
      >
        <span className="text-[28px] font-extrabold tracking-[-.5px] text-v-fg">
          {missed} target{missed === 1 ? "" : "s"} missed
        </span>
        <span className="text-sm text-v-body">out of {total}</span>
      </Card>

      <p className="text-xs text-v-muted">
        Campaign: all calls · GPU: last 24h · Telephony when provider SLA is configured
      </p>

      <Card className="overflow-hidden p-0">
        <div className="flex items-center justify-between gap-3 border-b border-v-line px-4 py-3.5">
          <h3 className="text-[15px] font-semibold text-v-fg">
            Performance metrics agreed on
          </h3>
        </div>

        <div className="grid grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)] gap-3 border-b border-v-line px-3 py-2 text-[10px] font-mono uppercase tracking-[.12em] text-v-muted">
          <span>Measure</span>
          <span>Agreed target</span>
          <span>Actual</span>
        </div>

        <div className="flex flex-col">
          {sections.map((section, index) => (
            <div key={section.id} className="flex flex-col">
              {index > 0 ? <div className="h-px w-full bg-v-line" /> : null}
              <div className="px-4 pb-1 pt-4">
                <span className="font-mono text-[10px] uppercase tracking-[.14em] text-v-muted">
                  {section.title}
                </span>
              </div>
              <div className="flex flex-col px-1 pb-2">
                {section.metrics.map((metric) => (
                  <MetricRow key={metric.key} metric={metric} />
                ))}
              </div>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}
