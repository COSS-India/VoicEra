"use client";

import { useCallback, useRef, useState } from "react";
import { translateCallTranscriptViaLlm } from "@/lib/api/calls";
import { parseTranscript, type TranscriptLine } from "@/lib/transcript";
import { ApiError } from "@/lib/api-client";

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
  /** Resolves the expected number of lines after a correct backend
   * translation — a mismatch means the model corrupted the transcript's line
   * structure. Lazy: called inside this function's own try/catch, so any
   * fetch it does can't throw outside error handling. */
  resolveExpectedLineCount: () => Promise<number>;
  /** Builds a translated line from one parsed backend TranscriptLine. */
  fromParsedLine: (line: TranscriptLine) => TLine;
}

/**
 * Shared backend-LLM-translate parse/validate logic, previously duplicated
 * (and drifted) between CallStage and CallDetailSheet. The whole transcript
 * goes to the LLM in one request so every line is translated with the full
 * conversation as context (Chrome's on-device Translator was dropped: it
 * translates lines in isolation, which QA found mistranslates honorifics,
 * fillers, idioms, and who is speaking). Standardizes on the stricter structural check:
 * `parsedLines.length !== expectedLineCount` (CallStage previously only
 * checked `=== 0`, which misses a same-nonzero-but-wrong-count corruption).
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
    const { originalLines, callId, resolveExpectedLineCount, fromParsedLine } = options;
    if (originalLines.length === 0) return;

    const myRequest = (requestIdRef.current += 1);
    const isStale = () => requestIdRef.current !== myRequest;
    setLoading(true);
    setError("");

    try {
      if (!callId) {
        throw new Error("Transcript is still being saved — try again in a few seconds.");
      }
      const response = await translateCallTranscriptViaLlm(callId, targetLang);
      if (isStale()) return;
      const parsedLines = parseTranscript(response.translated_text);
      const expectedLineCount = await resolveExpectedLineCount();
      if (isStale()) return;
      if (parsedLines.length !== expectedLineCount) {
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
