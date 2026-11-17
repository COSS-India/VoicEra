"use client";

import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";
import {
  formatDurationSince,
  formatSlaClock,
  formatSlaTimestamp,
  serviceBadgeTone,
  serviceStatusLabel,
} from "@/lib/sla-format";
import type { SlaBaseDetailsResponse, SlaServiceCard } from "@/lib/sla-types";

const SERVICE_BLURBS: Record<string, string> = {
  hosting: "The computers everything runs on",
  telephony: "The phone connection into the service",
  stt: "Turns caller speech into text",
  llm: "Understands the request and decides what to say",
  tts: "Turns the reply into spoken audio",
  orchestrator: "Wires the call flow end to end",
};

function ServiceCard({ service }: { service: SlaServiceCard }) {
  const tone = serviceBadgeTone(service.status);
  const blurb = SERVICE_BLURBS[service.id] ?? service.rule ?? "";
  const isStage = service.id === "stt" || service.id === "llm" || service.id === "tts";

  return (
    <Card className="flex flex-col gap-3 p-4.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex flex-col gap-1">
          <span className="text-[15px] font-semibold text-v-fg">{service.label}</span>
          {blurb ? (
            <span className="text-xs font-light text-v-muted">{blurb}</span>
          ) : null}
        </div>
        <Badge tone={tone}>{serviceStatusLabel(service.status)}</Badge>
      </div>

      <div className="h-px w-full bg-v-line" />

      {service.status === "working" ? (
        <div className="grid grid-cols-2 gap-3 text-xs">
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-[9.5px] uppercase tracking-[.12em] text-v-muted">
              Active since
            </span>
            <span className="tabular-nums text-v-fg">
              {formatSlaClock(service.active_since)}
            </span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-[9.5px] uppercase tracking-[.12em] text-v-muted">
              For
            </span>
            <span className="tabular-nums text-v-fg">
              {formatDurationSince(service.duration_seconds)}
            </span>
          </div>
        </div>
      ) : null}

      {service.status === "not_working" ? (
        <div className="grid grid-cols-2 gap-3 text-xs">
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-[9.5px] uppercase tracking-[.12em] text-v-muted">
              Last worked at
            </span>
            <span className="tabular-nums text-v-fg">
              {formatSlaClock(service.down_since)}
            </span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-[9.5px] uppercase tracking-[.12em] text-v-muted">
              Not working for
            </span>
            <span className="tabular-nums font-medium text-v-danger">
              {formatDurationSince(service.duration_seconds)}
            </span>
          </div>
        </div>
      ) : null}

      {isStage && service.status === "running" ? (
        <div className="grid grid-cols-2 gap-3 text-xs">
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-[9.5px] uppercase tracking-[.12em] text-v-muted">
              Right now
            </span>
            <span className="text-v-fg">In progress</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-[9.5px] uppercase tracking-[.12em] text-v-muted">
              Call
            </span>
            <span className="text-v-fg">{service.call_happened ?? "—"}</span>
          </div>
        </div>
      ) : null}

      {isStage && service.status === "not_running" ? (
        <div className="grid grid-cols-2 gap-3 text-xs">
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-[9.5px] uppercase tracking-[.12em] text-v-muted">
              Last call
            </span>
            <span className="text-v-fg">{service.call_happened ?? "—"}</span>
          </div>
          <div className="flex flex-col gap-0.5">
            <span className="font-mono text-[9.5px] uppercase tracking-[.12em] text-v-muted">
              Ago
            </span>
            <span className="tabular-nums text-v-fg">
              {formatDurationSince(service.call_happened_ago_seconds)}
            </span>
          </div>
        </div>
      ) : null}

      {service.status === "unknown" ? (
        <span className="text-xs text-v-muted">Status unknown — no signal yet.</span>
      ) : null}
    </Card>
  );
}

export function SlaOverviewTab({ data }: { data: SlaBaseDetailsResponse }) {
  const summary = data.summary;
  const labelById = Object.fromEntries(data.services.map((s) => [s.id, s.label]));

  return (
    <div className="flex flex-col gap-5">
      {summary ? (
        <Card className="flex flex-col gap-4 border-v-danger-line bg-v-danger-pale/50 p-5">
          <div className="flex flex-col gap-1.5">
            <h3 className="text-[22px] font-extrabold tracking-[-.4px] text-v-fg">
              Callers may not get through right now
            </h3>
            <p className="text-sm text-v-body">
              One or more critical parts of the voice pipeline are not working
              normally for this campaign.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-v-muted">Affected</span>
            {summary.affected_services.map((id) => (
              <span
                key={id}
                className="rounded-full border border-v-line bg-v-panel px-2.5 py-1 text-[11px] font-medium text-v-fg"
              >
                {labelById[id] ?? id}
              </span>
            ))}
          </div>

          <div className="grid gap-3 border-t border-v-danger-line/40 pt-4 sm:grid-cols-3">
            <div className="flex flex-col gap-0.5">
              <span className="font-mono text-[9.5px] uppercase tracking-[.12em] text-v-muted">
                Started
              </span>
              <span className="text-sm tabular-nums text-v-fg">
                {formatSlaClock(summary.started_at)}
              </span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="font-mono text-[9.5px] uppercase tracking-[.12em] text-v-muted">
                Next update
              </span>
              <span className="text-sm tabular-nums text-v-fg">
                {formatSlaClock(summary.next_update_at)}
              </span>
            </div>
            <div className="flex flex-col gap-0.5">
              <span className="font-mono text-[9.5px] uppercase tracking-[.12em] text-v-muted">
                Expected fix by
              </span>
              <span className="text-sm tabular-nums text-v-fg">
                {formatSlaClock(summary.expected_fix_by)}
              </span>
            </div>
          </div>
        </Card>
      ) : null}

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold text-v-fg">Details</h3>
        <div className="grid gap-3 md:grid-cols-2">
          {data.services.map((service) => (
            <ServiceCard key={service.id} service={service} />
          ))}
        </div>
      </div>

      <p className="text-xs text-v-muted">
        Pipeline last active:{" "}
        <span className="tabular-nums text-v-body">
          {formatSlaTimestamp(data.pipeline_last_active_at)}
        </span>
      </p>
    </div>
  );
}
