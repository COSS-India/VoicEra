import { apiFetch } from "@/lib/api/http";

export interface HoldAudioUploadResult {
  clip_id: string;
  storage_key: string;
  filename: string;
}

/** WAV or MP3, up to the backend's HOLD_AUDIO_MAX_UPLOAD_BYTES (2 MB). */
export async function uploadHoldAudio(file: File): Promise<HoldAudioUploadResult> {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetch<HoldAudioUploadResult>("/hold-audio/upload", {
    method: "POST",
    body: formData,
  });
}

export async function deleteHoldAudio(
  clipId: string,
  storageKey: string,
): Promise<{ deleted: boolean }> {
  const params = new URLSearchParams({ storage_key: storageKey });
  return apiFetch<{ deleted: boolean }>(
    `/hold-audio/${encodeURIComponent(clipId)}?${params.toString()}`,
    { method: "DELETE" },
  );
}
