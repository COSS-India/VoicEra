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
  { limit = 50, offset = 0 }: { limit?: number; offset?: number } = {},
): Promise<CallLogListResponse> {
  return apiFetch<CallLogListResponse>(
    `/calls/org/${encodeURIComponent(orgId)}?limit=${limit}&offset=${offset}`,
  );
}

/** Pages through the whole org — for bulk exports, where "all calls"/"all
 * transcripts" means every call, not just the page currently on screen. */
export async function listAllOrgCalls(orgId: string, pageSize = 100): Promise<CallLogItem[]> {
  const all: CallLogItem[] = [];
  let offset = 0;
  for (;;) {
    const res = await listOrgCalls(orgId, { limit: pageSize, offset });
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
