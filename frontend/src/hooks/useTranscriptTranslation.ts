"use client";

import { useCallback, useRef, useState } from "react";
import { translateCallTranscriptViaLlm } from "@/lib/api/calls";
import { parseTranscript, type TranscriptLine } from "@/lib/transcript";
import { ApiError } from "@/lib/api-client";

// The backend allows one in-flight translation per call + language and
// answers duplicates with 409 (no LLM call, no quota). Retrying lands on the
// cached result once the first request finishes; 20 × 3s outlasts a slow LLM.
const IN_PROGRESS_RETRY_MS = 3_000;
const IN_PROGRESS_MAX_RETRIES = 20;

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

interface TranslationResult<TLine> {
  lines: TLine[];
  lang: string;
}

interface TranslateOptions<TLine> {
  /** The on-screen lines; translation is skipped when there are none. */
  originalLines: readonly unknown[];
  /** The callId whose persisted transcript the backend translates, or
   * undefined if the call hasn't been saved yet. */
  callId: string | undefined;
  /** Builds a translated line from one parsed backend TranscriptLine. */
  fromParsedLine: (line: TranscriptLine) => TLine;
}

/**
 * Shared backend-LLM-translate parse/validate logic, previously duplicated
 * (and drifted) between CallStage and CallDetailSheet. The whole transcript
 * goes to the LLM in one request so every line is translated with the full
 * conversation as context (Chrome's on-device Translator was dropped: it
 * translates lines in isolation, which QA found mistranslates honorifics,
 * fillers, idioms, and who is speaking). The backend rejects any response
 * whose line count differs from the persisted transcript, so no client-side
 * re-check (which needed a second fetch after the paid LLM call) is done here.
 */
export function useTranscriptTranslation<TLine>() {
  const [result, setResult] = useState<TranslationResult<TLine> | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [showing, setShowing] = useState(false);
  const requestIdRef = useRef(0);

  const reset = useCallback(() => {
    requestIdRef.current += 1;
    setResult(null);
    setLoading(false);
    setError("");
    setShowing(false);
  }, []);

  function hasCachedTranslation(targetLang: string): boolean {
    return result !== null && result.lang === targetLang;
  }

  async function translate(targetLang: string, options: TranslateOptions<TLine>) {
    const { originalLines, callId, fromParsedLine } = options;
    if (originalLines.length === 0) return;

    const myRequest = (requestIdRef.current += 1);
    const isStale = () => requestIdRef.current !== myRequest;
    setLoading(true);
    setError("");

    try {
      if (!callId) {
        throw new Error("Transcript is still being saved — try again in a few seconds.");
      }
      let response: Awaited<ReturnType<typeof translateCallTranscriptViaLlm>> | undefined;
      for (let attempt = 0; response === undefined; attempt += 1) {
        try {
          response = await translateCallTranscriptViaLlm(callId, targetLang);
        } catch (err) {
          if (!(err instanceof ApiError && err.status === 409)) throw err;
          if (attempt >= IN_PROGRESS_MAX_RETRIES) {
            throw new Error("Translation is taking longer than expected. Please try again.");
          }
          await sleep(IN_PROGRESS_RETRY_MS);
          if (isStale()) return;
        }
      }
      if (isStale()) return;
      const parsedLines = parseTranscript(response.translated_text);
      if (parsedLines.length === 0) {
        setError("The translation model corrupted the transcript format. Please try again.");
        return;
      }
      setResult({ lines: parsedLines.map(fromParsedLine), lang: response.target_lang });
      setShowing(true);
    } catch (err) {
      if (isStale()) return;
      const message =
        err instanceof ApiError && err.status === 404
          ? "Transcript is still being saved — try again in a few seconds."
          : err instanceof Error
            ? err.message
            : "Failed to translate transcript. Please try again.";
      setError(message);
    } finally {
      if (!isStale()) setLoading(false);
    }
  }

  return { result, loading, error, showing, setShowing, translate, reset, hasCachedTranslation };
}
