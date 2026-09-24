"use client";

import { useCallback, useRef, useState } from "react";
import {
  detectTextLanguage,
  isChromeTranslationAvailable,
  isTranslationPairAvailable,
  translateLines,
} from "@/lib/chrome-translation";
import { translateCallTranscriptViaLlm } from "@/lib/api/calls";
import { parseTranscript, type TranscriptLine } from "@/lib/transcript";
import { ApiError } from "@/lib/api-client";

interface TranslationResult<TLine> {
  lines: TLine[];
  lang: string;
}

interface TranslateOptions<TLine, TOriginal extends { content: string }> {
  /** The lines to translate, in on-screen order. */
  originalLines: TOriginal[];
  /** Rebuilds a translated line from the original at the same index and its
   * translated text — used for the on-device path, which preserves order/count. */
  zipOnDeviceLine: (original: TOriginal, translatedText: string, index: number) => TLine;
  /** The callId to translate via the backend LLM fallback, or undefined if
   * no call is associated yet (on-device-only translation still works). */
  callId: string | undefined;
  /** Resolves the expected number of lines after a correct backend
   * translation — a mismatch means the model corrupted the transcript's line
   * structure. Lazy: only called on the LLM-fallback path, inside this
   * function's own try/catch, so any fetch it does can't throw ahead of the
   * on-device path or outside error handling. */
  resolveExpectedLineCount: () => Promise<number>;
  /** Builds a translated line from one parsed backend TranscriptLine. */
  fromParsedLine: (line: TranscriptLine) => TLine;
}

/**
 * Shared backend-LLM-translate parse/validate + on-device Chrome Translator
 * logic, previously duplicated (and drifted) between CallStage and
 * CallDetailSheet. Standardizes on the stricter structural check:
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

  async function translate<TOriginal extends { content: string }>(
    targetLang: string,
    options: TranslateOptions<TLine, TOriginal>,
  ) {
    const { originalLines, zipOnDeviceLine, callId, resolveExpectedLineCount, fromParsedLine } = options;
    if (originalLines.length === 0) return;

    const myRequest = (requestIdRef.current += 1);
    const isStale = () => requestIdRef.current !== myRequest;
    setLoading(true);
    setError("");

    try {
      if (isChromeTranslationAvailable()) {
        // Detection runs once on the whole joined transcript, not per line —
        // a code-switched call (e.g. Hinglish, Marathi/English mixed within
        // one transcript) gets one detected source language applied to every
        // line below, so some lines may translate from the wrong assumed
        // source. Per-line detection would fix this but multiplies detector
        // calls per transcript; out of scope for now.
        const sampleText = originalLines.map((l) => l.content).join("\n");
        const detected = await detectTextLanguage(sampleText);
        const sourceLanguage = detected?.language;
        const pairSupported = sourceLanguage
          ? await isTranslationPairAvailable(sourceLanguage, targetLang)
          : false;

        if (sourceLanguage && pairSupported) {
          const texts = await translateLines(
            originalLines.map((l) => l.content),
            sourceLanguage,
            targetLang,
          );
          if (isStale()) return;
          const lines = originalLines.map((line, i) => zipOnDeviceLine(line, texts[i] ?? line.content, i));
          setResult({ lines, lang: targetLang });
          setShowing(true);
          return; // free on-device path — no backend call made
        }
      }

      if (!callId) {
        throw new Error("On-device translation isn't available in this browser for this language.");
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
