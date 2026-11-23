"use client";

import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Download } from "lucide-react";
import { useAuth } from "@/components/AuthProvider";
import { listAgents } from "@/lib/api-client";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { Spinner } from "@/components/ui/Spinner";
import {
  exportAuditEventsCsv,
  listAuditEvents,
  listAuditEventTypes,
  type AuditEventQuery,
} from "@/lib/api/events";
import type { AgentApiResponse, AuditEvent, AuditEventType, AuditResource } from "@/lib/api-types";
import { isOrgAdmin } from "@/lib/auth-storage";
import { formatDateTime, formatUserRole } from "@/lib/format";
import { downloadBlob } from "@/lib/report";

const PAGE_SIZE = 50;

type Filters = { type: string; actor: string; target: string; agent: string; from: string; to: string };

const EMPTY_FILTERS: Filters = { type: "", actor: "", target: "", agent: "", from: "", to: "" };

const inputClass =
  "h-9 rounded-v-sm border border-v-line bg-v-soft/80 px-3 text-[13px] transition-colors placeholder:text-v-muted focus:border-v-accent focus:bg-white focus:outline-none";

/** Date inputs are local calendar days; the API takes inclusive ISO bounds. */
function toQuery(filters: Filters): AuditEventQuery {
  return {
    types: filters.type ? [filters.type] : undefined,
    actor_id: filters.actor,
    target_id: filters.target,
    resource: filters.agent ? `agent:${filters.agent}` : undefined,
    from: filters.from ? new Date(`${filters.from}T00:00:00`).toISOString() : undefined,
    to: filters.to ? new Date(`${filters.to}T23:59:59`).toISOString() : undefined,
  };
}

/** Raw `context`/`data` keys (`user_agent`) read as labels (`user agent`). */
const fieldLabel = (key: string) => key.replace(/_/g, " ");

/** Current agent names by id, used when an event recorded no name. */
type CurrentNames = Map<string, string>;

/** Resource types (`phone_number`) read as labels (`Phone number`). */
function resourceTypeLabel(type: string): string {
  const label = fieldLabel(type);
  return label.charAt(0).toUpperCase() + label.slice(1);
}

function currentName(resource: AuditResource, names: CurrentNames): string | undefined {
  return resource.type === "agent" ? names.get(resource.id) : undefined;
}

/** Name recorded on the event, else the current name, else the id. */
function resourceName(resource: AuditResource, names: CurrentNames): string {
  return resource.name ?? currentName(resource, names) ?? resource.id;
}

function resourceRows(resource: AuditResource, names: CurrentNames): [string, string][] {
  const label = resourceTypeLabel(resource.type);
  const rows: [string, string][] = [];
  const name = resourceName(resource, names);
  // Without any name, the id is shown once, as "<Type> ID".
  if (name !== resource.id) rows.push([label, name]);
  const current = currentName(resource, names);
  if (resource.name && current && current !== resource.name) rows.push([`${label} (current name)`, current]);
  rows.push([`${label} ID`, resource.id]);
  return rows;
}

function EventDetails({ event, currentNames }: { event: AuditEvent; currentNames: CurrentNames }) {
  const rows: [string, string][] = [
    ["Timestamp (UTC)", event.ts],
    ["Event ID", event.id],
    ["Event type", event.type],
    ...(event.target ? resourceRows(event.target, currentNames) : []),
    ...event.related.flatMap((resource) => resourceRows(resource, currentNames)),
    ["Actor type", event.actor.type],
    ["Actor role", event.actor.role ? formatUserRole(event.actor.role) : "–"],
    ...Object.entries(event.context).map(([k, v]): [string, string] => [fieldLabel(k), v]),
    ...Object.entries(event.data).map(([k, v]): [string, string] => [
      fieldLabel(k),
      typeof v === "string" ? v : JSON.stringify(v),
    ]),
  ];
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1.5">
      {rows.map(([label, value], i) => (
        <Fragment key={`${i}-${label}`}>
          <dt className="font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">{label}</dt>
          <dd className="min-w-0 break-all text-[12.5px] text-v-fg">{value}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

export function AuditLog() {
  const { session } = useAuth();
  const isAdmin = isOrgAdmin(session);

  const [types, setTypes] = useState<AuditEventType[]>([]);
  const [agents, setAgents] = useState<AgentApiResponse[]>([]);
  /** Incremented on each filter change to discard stale "Load more" responses. */
  const generation = useRef(0);
  const [draft, setDraft] = useState<Filters>(EMPTY_FILTERS);
  const [applied, setApplied] = useState<Filters>(EMPTY_FILTERS);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const describe = (name: string) => types.find((t) => t.name === name)?.description ?? name;
  const currentNames = useMemo(() => new Map(agents.map((a) => [a.agent_id, a.name])), [agents]);

  useEffect(() => {
    if (!isAdmin) return;
    listAuditEventTypes()
      .then(setTypes)
      .catch(() => {
        /* Non-fatal: the type filter offers only "All events". */
      });
    listAgents()
      .then(setAgents)
      .catch(() => {
        /* Non-fatal: the agent filter is hidden; events still show recorded names. */
      });
  }, [isAdmin]);

  useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    listAuditEvents({ ...toQuery(applied), limit: PAGE_SIZE })
      .then((page) => {
        if (cancelled) return;
        setEvents(page.events);
        setCursor(page.next_cursor);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load the audit log.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [applied, isAdmin]);

  function apply(filters: Filters) {
    generation.current += 1;
    // Clear results and cursor from the previous filters.
    setEvents([]);
    setCursor(null);
    setLoading(true);
    setLoadingMore(false);
    setError("");
    setExpanded(null);
    setApplied(filters);
  }

  function loadMore() {
    if (!cursor) return;
    const requested = generation.current;
    const isCurrent = () => requested === generation.current;
    setLoadingMore(true);
    listAuditEvents({ ...toQuery(applied), limit: PAGE_SIZE, cursor })
      .then((page) => {
        if (!isCurrent()) return;
        setEvents((prev) => [...prev, ...page.events]);
        setCursor(page.next_cursor);
      })
      .catch((err) => {
        if (isCurrent()) setError(err instanceof Error ? err.message : "Could not load more events.");
      })
      .finally(() => {
        if (isCurrent()) setLoadingMore(false);
      });
  }

  function exportCsv() {
    setExporting(true);
    exportAuditEventsCsv(toQuery(applied))
      .then((blob) =>
        downloadBlob(blob, "text/csv;charset=utf-8", `audit-log-${new Date().toISOString().slice(0, 10)}.csv`),
      )
      .catch((err) => setError(err instanceof Error ? err.message : "Could not export the audit log."))
      .finally(() => setExporting(false));
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1.5 border-b border-v-line pb-6">
        <h1 className="text-3xl font-semibold tracking-tight">Audit log</h1>
        <p className="max-w-[62ch] text-sm font-light leading-relaxed text-v-muted">
          Activity in your organisation, including who did what and when.
        </p>
      </div>

      {!isAdmin ? (
        <p className="text-sm text-v-muted">Only organisation admins can view the audit log.</p>
      ) : (
        <>
          <form
            className="flex flex-wrap items-end gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              apply({ ...draft });
            }}
          >
            <Select
              size="sm"
              aria-label="Event type"
              className="!h-9 !py-0"
              value={draft.type}
              onChange={(e) => setDraft((d) => ({ ...d, type: e.target.value }))}
            >
              <option value="">All events</option>
              {types.map((t) => (
                <option key={t.name} value={t.name}>
                  {t.description}
                </option>
              ))}
            </Select>
            {agents.length > 0 ? (
              <Select
                size="sm"
                aria-label="Agent"
                className="!h-9 !py-0 min-w-[10rem] max-w-[14rem]"
                value={draft.agent}
                onChange={(e) => setDraft((d) => ({ ...d, agent: e.target.value }))}
              >
                <option value="">All agents</option>
                {agents.map((a) => (
                  <option key={a.agent_id} value={a.agent_id}>
                    {a.name}
                  </option>
                ))}
              </Select>
            ) : null}
            <input
              type="search"
              placeholder="Actor email"
              aria-label="Actor email"
              value={draft.actor}
              onChange={(e) => setDraft((d) => ({ ...d, actor: e.target.value }))}
              className={inputClass}
            />
            <input
              type="search"
              placeholder="Target ID"
              aria-label="Target ID"
              value={draft.target}
              onChange={(e) => setDraft((d) => ({ ...d, target: e.target.value }))}
              className={inputClass}
            />
            <input
              type="date"
              aria-label="From date"
              value={draft.from}
              onChange={(e) => setDraft((d) => ({ ...d, from: e.target.value }))}
              className={inputClass}
            />
            <input
              type="date"
              aria-label="To date"
              value={draft.to}
              onChange={(e) => setDraft((d) => ({ ...d, to: e.target.value }))}
              className={inputClass}
            />
            <Button type="submit" size="sm" variant="dark">
              Apply
            </Button>
            <div className="flex-1" />
            <Button type="button" size="sm" variant="ghost" onClick={exportCsv} disabled={exporting}>
              {exporting ? <Spinner light={false} /> : <Download className="size-4" strokeWidth={1.75} />}
              Export CSV
            </Button>
          </form>
          <p className="-mt-3 text-xs text-v-muted">Shows the last 30 days unless a date range is set. A range can span at most 366 days.</p>

          {error ? (
            <div className="rounded-v-md border border-v-danger-line bg-v-danger-pale px-4 py-3 text-sm text-v-danger">
              {error}
            </div>
          ) : null}

          {loading ? (
            <div className="flex items-center justify-center gap-2 py-12 text-sm text-v-muted">
              <Spinner light={false} /> Loading audit log…
            </div>
          ) : events.length === 0 ? (
            <p className="py-12 text-center text-sm text-v-muted">No events match these filters.</p>
          ) : (
            <div className="overflow-x-auto rounded-v-md border border-v-line bg-white">
              <table className="w-full text-left text-[13px]">
                <thead className="border-b border-v-line bg-v-soft/60 font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">
                  <tr>
                    <th className="w-8 px-3 py-2.5" />
                    <th className="px-3 py-2.5 font-medium">Time</th>
                    <th className="px-3 py-2.5 font-medium">Actor</th>
                    <th className="px-3 py-2.5 font-medium">Event</th>
                    <th className="px-3 py-2.5 font-medium">Target</th>
                    <th className="px-3 py-2.5 font-medium">Related</th>
                    <th className="px-3 py-2.5 font-medium">Outcome</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((event) => {
                    const open = expanded === event.id;
                    return (
                      <Fragment key={event.id}>
                        <tr
                          onClick={() => setExpanded(open ? null : event.id)}
                          aria-expanded={open}
                          className="cursor-pointer border-b border-v-line last:border-b-0 hover:bg-v-soft/50"
                        >
                          <td className="px-3 py-2.5 text-v-muted">
                            {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
                          </td>
                          <td className="whitespace-nowrap px-3 py-2.5 text-v-muted-2">{formatDateTime(event.ts, { seconds: true })}</td>
                          <td className="px-3 py-2.5">{event.actor.id}</td>
                          <td className="px-3 py-2.5">{describe(event.type)}</td>
                          <td className="px-3 py-2.5 font-mono text-[12px] text-v-muted-2">
                            {event.target ? `${event.target.type} ${resourceName(event.target, currentNames)}` : "–"}
                          </td>
                          <td className="px-3 py-2.5">
                            {event.related.length === 0
                              ? "–"
                              : event.related.map((resource) => (
                                  <div key={`${resource.type}:${resource.id}`} className="whitespace-nowrap">
                                    <span className="text-v-muted">{resourceTypeLabel(resource.type)}:</span>{" "}
                                    {resourceName(resource, currentNames)}
                                  </div>
                                ))}
                          </td>
                          <td className="px-3 py-2.5">
                            <Badge tone={event.outcome === "success" ? "live" : "danger"}>{event.outcome}</Badge>
                          </td>
                        </tr>
                        {open ? (
                          <tr className="border-b border-v-line bg-v-soft/30">
                            <td />
                            <td colSpan={6} className="px-3 py-3">
                              <EventDetails event={event} currentNames={currentNames} />
                            </td>
                          </tr>
                        ) : null}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {cursor && !loading ? (
            <Button type="button" variant="ghost" size="sm" className="self-center" onClick={loadMore} disabled={loadingMore}>
              {loadingMore ? <Spinner light={false} /> : null}
              Load more
            </Button>
          ) : null}
        </>
      )}
    </div>
  );
}
