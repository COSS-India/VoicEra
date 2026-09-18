/**
 * Wrapper around Chrome's built-in, on-device Translator / Language
 * Detection APIs (Origin Trial tokens registered in src/app/layout.tsx).
 * Free and instant when available — the primary path in the hybrid
 * translate-call-transcript feature, with a server-side LLM fallback
 * (see lib/api/calls.ts `translateCallTranscriptViaLlm`) for browsers or
 * language pairs this can't cover.
 *
 * Namespace caveat: the exact global this API is exposed under has moved
 * across Chrome versions/origin-trial phases. `getTranslatorApi` /
 * `getLanguageDetectorApi` below normalize multiple candidate shapes seen
 * during development so the rest of this file only targets one interface —
 * confirm the real shape against the live target Chrome version before
 * relying on this in production; a wrong/stale candidate doesn't error, it
 * just makes `isChromeTranslationAvailable` report false and every request
 * silently falls back to the paid LLM path.
 */

export interface DetectedLanguage {
  language: string;
  confidence: number;
}

interface TranslatorSession {
  translate(text: string): Promise<string>;
  destroy?(): void;
}

interface DetectorSession {
  detect(text: string): Promise<{ detectedLanguage: string; confidence: number }[]>;
  destroy?(): void;
}

interface NormalizedTranslatorApi {
  availability(opts: { sourceLanguage: string; targetLanguage: string }): Promise<string>;
  createTranslator(opts: { sourceLanguage: string; targetLanguage: string }): Promise<TranslatorSession>;
}

interface NormalizedDetectorApi {
  createDetector(): Promise<DetectorSession>;
}

const DETECT_SAMPLE_MAX_CHARS = 2000;
const UNDETERMINED_LANGUAGE = "und";

function getTranslatorApi(): NormalizedTranslatorApi | null {
  const g = globalThis as unknown as {
    Translator?: { availability: NormalizedTranslatorApi["availability"]; create: NormalizedTranslatorApi["createTranslator"] };
    translation?: { createTranslator?: NormalizedTranslatorApi["createTranslator"] };
  };
  if (g.Translator) {
    return {
      availability: (opts) => g.Translator!.availability(opts),
      createTranslator: (opts) => g.Translator!.create(opts),
    };
  }
  if (g.translation?.createTranslator) {
    const createTranslator = g.translation.createTranslator;
    return {
      availability: async (opts) => {
        try {
          await createTranslator(opts);
          return "available";
        } catch {
          return "unavailable";
        }
      },
      createTranslator,
    };
  }
  return null;
}

function getLanguageDetectorApi(): NormalizedDetectorApi | null {
  const g = globalThis as unknown as {
    LanguageDetector?: { create(): Promise<DetectorSession> };
    translation?: { createDetector?(): Promise<DetectorSession> };
  };
  if (g.LanguageDetector) return { createDetector: () => g.LanguageDetector!.create() };
  if (g.translation?.createDetector) return { createDetector: g.translation.createDetector };
  return null;
}

export function isChromeTranslationAvailable(): boolean {
  return getTranslatorApi() != null;
}

export async function detectTextLanguage(text: string): Promise<DetectedLanguage | null> {
  const detectorApi = getLanguageDetectorApi();
  if (!detectorApi) return null;

  let detector;
  try {
    detector = await detectorApi.createDetector();
  } catch {
    // Some Chromium forks (e.g. Brave) expose the LanguageDetector global but
    // disable the underlying on-device model, so create() throws instead of
    // never existing. Treat that the same as "no detector" so callers fall
    // back to the LLM path instead of surfacing a raw browser error.
    return null;
  }
  try {
    const sample = text.slice(0, DETECT_SAMPLE_MAX_CHARS);
    const results = await detector.detect(sample);
    const topResult = results[0];
    if (!topResult || topResult.detectedLanguage === UNDETERMINED_LANGUAGE) return null;
    return { language: topResult.detectedLanguage, confidence: topResult.confidence };
  } finally {
    detector.destroy?.();
  }
}

/** `availability()` resolves to "available", "downloadable", "downloading",
 * "unavailable", or `null` when support couldn't be determined — only the
 * first three mean the pair can actually be used (the model downloads
 * automatically inside `createTranslator`/`Translator.create()` on first use). */
const SUPPORTED_AVAILABILITY_STATES = new Set(["available", "downloadable", "downloading"]);

export async function isTranslationPairAvailable(sourceLanguage: string, targetLanguage: string): Promise<boolean> {
  const translatorApi = getTranslatorApi();
  if (!translatorApi) return false;
  try {
    const availability = await translatorApi.availability({ sourceLanguage, targetLanguage });
    return SUPPORTED_AVAILABILITY_STATES.has(availability);
  } catch {
    // Some Chromium forks (e.g. Brave) expose the Translator global but disable
    // the underlying on-device model, so availability() throws instead of
    // resolving "unavailable". Treat that the same as unsupported so callers
    // fall back to the LLM path instead of surfacing a raw browser error.
    return false;
  }
}

/**
 * Translates each line independently, preserving array order and length.
 * Blank/whitespace-only lines are returned unchanged rather than sent to
 * the model. Throws if the Translator API is unavailable — callers must
 * check `isTranslationPairAvailable` first and treat a throw here as a
 * real failure, never as an implicit "fall back silently" signal.
 */
export async function translateLines(
  lines: readonly string[],
  sourceLanguage: string,
  targetLanguage: string,
): Promise<string[]> {
  const translatorApi = getTranslatorApi();
  if (!translatorApi) throw new Error("Chrome Translator API is not available.");

  const translator = await translatorApi.createTranslator({ sourceLanguage, targetLanguage });
  try {
    const translatedLines: string[] = [];
    for (const line of lines) {
      const trimmed = line.trim();
      translatedLines.push(trimmed ? await translator.translate(trimmed) : line);
    }
    return translatedLines;
  } finally {
    translator.destroy?.();
  }
}
