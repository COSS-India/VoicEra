import { apiFetch, apiFetchBlob } from "@/lib/api/http";
import type {
  CallAnalyticsResponse,
  CallLogItem,
  CallLogListResponse,
  CallMetricsResponse,
  OutboundCallRequest,
  OutboundCallResponse,
  WebCallRegisterRequest,
  WebCallRegisterResponse,
} from "@/lib/api-types";

export type CallListQuery = {
  limit?: number;
  offset?: number;
  campaign_id?: string;
  exclude_campaign?: boolean;
  agent_id?: string;
  status?: string;
  call_type?: string;
  call_response?: string;
  created_after?: string;
  created_before?: string;
};

function buildCallListQuery(params: CallListQuery): string {
  const q = new URLSearchParams();
  if (params.limit != null) q.set("limit", String(params.limit));
  if (params.offset != null) q.set("offset", String(params.offset));
  if (params.campaign_id) q.set("campaign_id", params.campaign_id);
  if (params.exclude_campaign) q.set("exclude_campaign", "true");
  if (params.agent_id) q.set("agent_id", params.agent_id);
  if (params.status && params.status !== "all") q.set("status", params.status);
  if (params.call_type && params.call_type !== "all") q.set("call_type", params.call_type);
  if (params.call_response) q.set("call_response", params.call_response);
  if (params.created_after) q.set("created_after", params.created_after);
  if (params.created_before) q.set("created_before", params.created_before);
  const s = q.toString();
  return s ? `?${s}` : "";
}

/** Places a real outbound call from the agent's linked number to `to_number`. */
export async function createOutboundCall(payload: OutboundCallRequest): Promise<OutboundCallResponse> {
  return apiFetch<OutboundCallResponse>("/calls/outbound", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** Registers a browser-websocket test session as a CallLog before connecting, so
 * the runtime's /agent websocket route (passed this call_id as a query param)
 * persists the recording/transcript the same way a telephony call does. */
export async function createWebCall(payload: WebCallRegisterRequest): Promise<WebCallRegisterResponse> {
  return apiFetch<WebCallRegisterResponse>("/calls/web", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listOrgCalls(
  orgId: string,
  params: CallListQuery = {},
): Promise<CallLogListResponse> {
  const { limit = 50, offset = 0, ...filters } = params;
  return apiFetch<CallLogListResponse>(
    `/calls/org/${encodeURIComponent(orgId)}${buildCallListQuery({ limit, offset, ...filters })}`,
  );
}

/** Pages through matching org calls — for bulk exports. */
export async function listAllOrgCalls(
  orgId: string,
  filters: Omit<CallListQuery, "limit" | "offset"> = {},
  pageSize = 100,
): Promise<CallLogItem[]> {
  const all: CallLogItem[] = [];
  let offset = 0;
  for (;;) {
    const res = await listOrgCalls(orgId, { ...filters, limit: pageSize, offset });
    all.push(...res.calls);
    offset += res.calls.length;
    if (res.calls.length === 0 || offset >= res.total) break;
  }
  return all;
}

/** Fetches one call by id directly — used when a link (e.g. "Show telemetry"
 * from the call detail sheet) needs a specific call regardless of which page
 * of the org's call list it falls on. */
export async function getCall(callId: string): Promise<CallLogItem> {
  return apiFetch<CallLogItem>(`/calls/${encodeURIComponent(callId)}`);
}

/** Recording is a bearer-authenticated MinIO proxy — fetch as a blob, since
 * <audio src> can't send auth headers. Callers derive an object URL for playback
 * and decode the same blob for waveform peaks. */
export async function fetchCallRecordingBlob(callId: string): Promise<Blob> {
  return apiFetchBlob(`/calls/${encodeURIComponent(callId)}/recording`);
}

export async function fetchCallTranscriptText(callId: string): Promise<string> {
  const blob = await apiFetchBlob(`/calls/${encodeURIComponent(callId)}/transcript`);
  return blob.text();
}

/** Pipeline latency metrics recorded by the runtime at call end. 404s (call not
 * found, or metrics not yet recorded) — callers should treat that as "no data"
 * for this call rather than a page-level error. */
export async function getCallMetrics(callId: string): Promise<CallMetricsResponse> {
  return apiFetch<CallMetricsResponse>(`/calls/${encodeURIComponent(callId)}/metrics`);
}

/** All-time org call analytics — total calls, average duration, most-used agent. */
export async function getOrgCallAnalytics(orgId: string): Promise<CallAnalyticsResponse> {
  return apiFetch<CallAnalyticsResponse>(`/calls/org/${encodeURIComponent(orgId)}/analytics`);
}
