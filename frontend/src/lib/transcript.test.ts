import { describe, expect, it } from "vitest";
import { translationTargetLang } from "@/lib/transcript";

describe("translationTargetLang", () => {
  it("keeps a supported browser language as its base code", () => {
    expect(translationTargetLang("hi-IN")).toBe("hi");
    expect(translationTargetLang("en-US")).toBe("en");
    expect(translationTargetLang("or")).toBe("or");
  });

  it("falls back to English for languages the backend doesn't serve", () => {
    expect(translationTargetLang("fr-FR")).toBe("en");
    expect(translationTargetLang("qq")).toBe("en");
    expect(translationTargetLang("")).toBe("en");
  });
});
