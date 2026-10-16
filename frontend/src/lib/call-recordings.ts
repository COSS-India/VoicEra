/**
 * Resolve which call recording artifact to use.
 *
 * System (`recording_url`) and provider (`provider_recording_url`) are parallel
 * fields from the API — no provider-id hardcoding required.
 */

export type CallRecordingKind = "system" | "provider";

export interface CallRecordingSource {
  kind: CallRecordingKind;
  label: string;
  /** API path under /api/v1 (no prefix). */
  apiPath: (callId: string) => string;
}

const SOURCES: CallRecordingSource[] = [
  {
    kind: "system",
    label: "System",
    apiPath: (callId) => `/calls/${encodeURIComponent(callId)}/recording`,
  },
  {
    kind: "provider",
    label: "Provider",
    apiPath: (callId) => `/calls/${encodeURIComponent(callId)}/provider-recording`,
  },
];

type RecordingFields = {
  recording_url?: string | null;
  provider_recording_url?: string | null;
};

function hasUrl(url: unknown): boolean {
  return typeof url === "string" && url.trim().length > 0;
}

function urlForKind(call: RecordingFields, kind: CallRecordingKind): unknown {
  return kind === "system" ? call.recording_url : call.provider_recording_url;
}

/** All recording kinds present on this call (system first, then provider). */
export function availableCallRecordings(call: RecordingFields): CallRecordingSource[] {
  return SOURCES.filter((s) => hasUrl(urlForKind(call, s.kind)));
}

export function callHasAnyRecording(call: RecordingFields): boolean {
  return availableCallRecordings(call).length > 0;
}
