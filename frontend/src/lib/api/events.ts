import { apiFetch, apiFetchBlob } from "@/lib/api/http";
import type { AuditEventListResponse, AuditEventType } from "@/lib/api-types";

/** Audit log filters. `from`/`to` are ISO timestamps; the API defaults to the last 30 days. */
export type AuditEventQuery = {
  types?: string[];
  actor_id?: string;
  target_type?: string;
  target_id?: string;
  /** `type:id` of the target or any related resource, e.g. `agent:agent_123`. */
  resource?: string;
  from?: string;
  to?: string;
};

function buildQuery(params: AuditEventQuery & { limit?: number; cursor?: string }): string {
  const q = new URLSearchParams();
  for (const type of params.types ?? []) q.append("type", type);
  for (const key of ["actor_id", "target_type", "target_id", "resource", "from", "to", "cursor"] as const) {
    const value = params[key]?.trim();
    if (value) q.set(key, value);
  }
  if (params.limit != null) q.set("limit", String(params.limit));
  const s = q.toString();
  return s ? `?${s}` : "";
}

/** One page of audit events, newest first. Pass `next_cursor` back as `cursor`. */
export async function listAuditEvents(
  params: AuditEventQuery & { limit?: number; cursor?: string } = {},
): Promise<AuditEventListResponse> {
  return apiFetch<AuditEventListResponse>(`/events${buildQuery(params)}`);
}

export async function listAuditEventTypes(): Promise<AuditEventType[]> {
  return apiFetch<AuditEventType[]>("/events/types");
}

/** CSV of every matching event (server-capped). The export itself is audited. */
export async function exportAuditEventsCsv(params: AuditEventQuery = {}): Promise<Blob> {
  return apiFetchBlob(`/events/export${buildQuery(params)}`);
}
