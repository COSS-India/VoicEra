import { afterEach, describe, expect, it, vi } from "vitest";
import {
  detectTextLanguage,
  isChromeTranslationAvailable,
  isTranslationPairAvailable,
  translateLines,
} from "@/lib/chrome-translation";

type GlobalWithChromeApi = typeof globalThis & {
  Translator?: unknown;
  LanguageDetector?: unknown;
  translation?: unknown;
};

function clearChromeApis() {
  const g = globalThis as GlobalWithChromeApi;
  delete g.Translator;
  delete g.LanguageDetector;
  delete g.translation;
}

afterEach(() => {
  clearChromeApis();
  vi.restoreAllMocks();
});

describe("isChromeTranslationAvailable", () => {
  it("returns false when no Chrome translation API is present", () => {
    expect(isChromeTranslationAvailable()).toBe(false);
  });

  it("returns true when window.Translator is present", () => {
    (globalThis as GlobalWithChromeApi).Translator = {
      availability: vi.fn(),
      create: vi.fn(),
    };
    expect(isChromeTranslationAvailable()).toBe(true);
  });

  it("returns true when window.translation.createTranslator is present", () => {
    (globalThis as GlobalWithChromeApi).translation = {
      createTranslator: vi.fn(),
    };
    expect(isChromeTranslationAvailable()).toBe(true);
  });
});

describe("detectTextLanguage", () => {
  it("returns null when no detector API is present", async () => {
    expect(await detectTextLanguage("hello")).toBeNull();
  });

  it("returns the top detected language and confidence", async () => {
    const detect = vi.fn().mockResolvedValue([{ detectedLanguage: "hi", confidence: 0.92 }]);
    const destroy = vi.fn();
    (globalThis as GlobalWithChromeApi).LanguageDetector = {
      create: vi.fn().mockResolvedValue({ detect, destroy }),
    };

    const result = await detectTextLanguage("नमस्ते");
    expect(result).toEqual({ language: "hi", confidence: 0.92 });
    expect(destroy).toHaveBeenCalledOnce();
  });

  it("returns null when the detector reports the language as undetermined", async () => {
    const detect = vi.fn().mockResolvedValue([{ detectedLanguage: "und", confidence: 0.1 }]);
    (globalThis as GlobalWithChromeApi).LanguageDetector = {
      create: vi.fn().mockResolvedValue({ detect, destroy: vi.fn() }),
    };

    expect(await detectTextLanguage("???")).toBeNull();
  });

  it("returns null when detect() resolves with no results", async () => {
    const detect = vi.fn().mockResolvedValue([]);
    (globalThis as GlobalWithChromeApi).LanguageDetector = {
      create: vi.fn().mockResolvedValue({ detect, destroy: vi.fn() }),
    };

    expect(await detectTextLanguage("")).toBeNull();
  });

  it("truncates the sample to the first 2000 characters before detecting", async () => {
    const detect = vi.fn().mockResolvedValue([{ detectedLanguage: "en", confidence: 0.99 }]);
    (globalThis as GlobalWithChromeApi).LanguageDetector = {
      create: vi.fn().mockResolvedValue({ detect, destroy: vi.fn() }),
    };

    const longText = "a".repeat(5000);
    await detectTextLanguage(longText);

    expect(detect).toHaveBeenCalledWith("a".repeat(2000));
  });

  it("returns null (not throw) when createDetector() itself throws, e.g. Brave exposing the API but disabling the on-device model", async () => {
    (globalThis as GlobalWithChromeApi).LanguageDetector = {
      create: vi.fn().mockRejectedValue(new Error("Model not available")),
    };

    await expect(detectTextLanguage("text")).resolves.toBeNull();
  });

  it("destroys the detector even when detect() throws", async () => {
    const destroy = vi.fn();
    (globalThis as GlobalWithChromeApi).LanguageDetector = {
      create: vi.fn().mockResolvedValue({
        detect: vi.fn().mockRejectedValue(new Error("boom")),
        destroy,
      }),
    };

    await expect(detectTextLanguage("text")).rejects.toThrow("boom");
    expect(destroy).toHaveBeenCalledOnce();
  });
});

describe("isTranslationPairAvailable", () => {
  it("returns false when the Translator API is absent (routes to fallback, never throws)", async () => {
    expect(await isTranslationPairAvailable("hi", "en")).toBe(false);
  });

  it("returns true when availability() reports a supported pair", async () => {
    (globalThis as GlobalWithChromeApi).Translator = {
      availability: vi.fn().mockResolvedValue("available"),
      create: vi.fn(),
    };
    expect(await isTranslationPairAvailable("hi", "en")).toBe(true);
  });

  it("returns false when availability() reports unavailable", async () => {
    (globalThis as GlobalWithChromeApi).Translator = {
      availability: vi.fn().mockResolvedValue("unavailable"),
      create: vi.fn(),
    };
    expect(await isTranslationPairAvailable("bh", "en")).toBe(false);
  });

  it("returns true when availability() reports downloadable (model not yet fetched)", async () => {
    (globalThis as GlobalWithChromeApi).Translator = {
      availability: vi.fn().mockResolvedValue("downloadable"),
      create: vi.fn(),
    };
    expect(await isTranslationPairAvailable("en", "hi")).toBe(true);
  });

  it("returns true when availability() reports downloading (fetch already in progress)", async () => {
    (globalThis as GlobalWithChromeApi).Translator = {
      availability: vi.fn().mockResolvedValue("downloading"),
      create: vi.fn(),
    };
    expect(await isTranslationPairAvailable("en", "hi")).toBe(true);
  });

  it("returns false when availability() reports null (support undetermined)", async () => {
    (globalThis as GlobalWithChromeApi).Translator = {
      availability: vi.fn().mockResolvedValue(null),
      create: vi.fn(),
    };
    expect(await isTranslationPairAvailable("en", "hi")).toBe(false);
  });

  it("returns false (not throw) when availability() itself throws, e.g. Brave exposing the API but disabling the on-device model", async () => {
    (globalThis as GlobalWithChromeApi).Translator = {
      availability: vi.fn().mockRejectedValue(new Error("Model not available")),
      create: vi.fn(),
    };
    await expect(isTranslationPairAvailable("en", "hi")).resolves.toBe(false);
  });
});

describe("translateLines", () => {
  it("throws when the Translator API is unavailable, rather than silently no-op-ing", async () => {
    await expect(translateLines(["hello"], "en", "hi")).rejects.toThrow(
      "Chrome Translator API is not available.",
    );
  });

  it("translates non-blank lines and passes blank/whitespace-only lines through unchanged", async () => {
    const translate = vi.fn().mockImplementation(async (text: string) => `[${text}]`);
    const destroy = vi.fn();
    (globalThis as GlobalWithChromeApi).Translator = {
      availability: vi.fn(),
      create: vi.fn().mockResolvedValue({ translate, destroy }),
    };

    const result = await translateLines(["hello", "", "  ", "world"], "en", "hi");

    expect(result).toEqual(["[hello]", "", "  ", "[world]"]);
    expect(translate).toHaveBeenCalledTimes(2);
    expect(translate).toHaveBeenCalledWith("hello");
    expect(translate).toHaveBeenCalledWith("world");
  });

  it("preserves input order and length exactly", async () => {
    const translate = vi.fn().mockImplementation(async (text: string) => text.toUpperCase());
    (globalThis as GlobalWithChromeApi).Translator = {
      availability: vi.fn(),
      create: vi.fn().mockResolvedValue({ translate, destroy: vi.fn() }),
    };

    const input = ["a", "b", "c", "d", "e"];
    const result = await translateLines(input, "en", "hi");

    expect(result).toHaveLength(input.length);
    expect(result).toEqual(["A", "B", "C", "D", "E"]);
  });

  it("destroys the translator session even when translate() throws mid-loop", async () => {
    const destroy = vi.fn();
    const translate = vi
      .fn()
      .mockResolvedValueOnce("ok")
      .mockRejectedValueOnce(new Error("mid-loop failure"));
    (globalThis as GlobalWithChromeApi).Translator = {
      availability: vi.fn(),
      create: vi.fn().mockResolvedValue({ translate, destroy }),
    };

    await expect(translateLines(["first", "second", "third"], "en", "hi")).rejects.toThrow(
      "mid-loop failure",
    );
    expect(destroy).toHaveBeenCalledOnce();
  });
});
