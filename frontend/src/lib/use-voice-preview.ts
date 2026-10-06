"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, previewTts, type TtsPreviewBody } from "@/lib/api-client";
import { PREVIEW_MAX_CHARS } from "@/lib/voice-preview-text";

// Keyed by the server's error `code` (apps/api/app/routers/tts_preview.py),
// not status: 400 and 422 each cover several reasons. The server's message is
// developer-facing, so it's never shown. 401 never lands here — apiFetchBlob
// already clears the session and redirects.
const PREVIEW_ERROR_MESSAGES: Record<string, string> = {
  empty_text: "Enter some text to generate a preview.",
  oversized: `Preview text is limited to ${PREVIEW_MAX_CHARS} characters.`,
  invalid_config: "This voice configuration isn't valid. Check the voice settings.",
  unsupported_voice: "Preview is not available for this voice.",
  not_configured: "Connect this provider first.",
  no_active_org: "Select an organisation to preview voices.",
  rate_limited: "Too many previews, please wait a moment.",
  timeout: "Voice preview is taking longer than expected. Please try again.",
  upstream: "The voice provider returned an error. Please try again.",
};
const FALLBACK_ERROR = "Unable to generate voice preview. Please try again.";

export function previewErrorMessage(err: unknown): string {
  const code = err instanceof ApiError ? err.code : undefined;
  return (code && PREVIEW_ERROR_MESSAGES[code]) || FALLBACK_ERROR;
}

export type VoicePreviewStatus = "idle" | "loading" | "ready" | "error";

interface VoicePreviewState {
  status: VoicePreviewStatus;
  audioUrl: string | null;
  error: string | null;
}

const IDLE: VoicePreviewState = { status: "idle", audioUrl: null, error: null };

/** One in-flight preview at a time. `generate` aborts any previous request and
 * revokes the previous clip's object URL; `reset` does the same and returns to
 * idle (call it when voice/language/model/extras change so stale audio never
 * plays). Unmount aborts and revokes too. */
export function useVoicePreview() {
  const [state, setState] = useState<VoicePreviewState>(IDLE);
  const abortRef = useRef<AbortController | null>(null);
  const urlRef = useRef<string | null>(null);

  const release = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    if (urlRef.current) URL.revokeObjectURL(urlRef.current);
    urlRef.current = null;
  }, []);

  const reset = useCallback(() => {
    release();
    setState(IDLE);
  }, [release]);

  const generate = useCallback(
    async (body: TtsPreviewBody) => {
      release();
      const controller = new AbortController();
      abortRef.current = controller;
      setState({ status: "loading", audioUrl: null, error: null });
      try {
        const blob = await previewTts(body, controller.signal);
        if (controller.signal.aborted) return;
        const url = URL.createObjectURL(blob);
        urlRef.current = url;
        setState({ status: "ready", audioUrl: url, error: null });
      } catch (err) {
        if (controller.signal.aborted) return;
        setState({ status: "error", audioUrl: null, error: previewErrorMessage(err) });
      }
    },
    [release],
  );

  useEffect(() => release, [release]);

  return { ...state, generate, reset };
}
