import { describe, expect, it } from "vitest";
import type { ProviderSettingsCatalog } from "@/lib/catalog-types";
import { acceptsCustomValue, defaultModelId } from "@/lib/catalog-utils";

function settings(models: string[] | undefined, defaultModel?: string): ProviderSettingsCatalog {
  return {
    provider: "p",
    name: "p",
    fields: { model: { type: "string", default: defaultModel, examples: models } },
  };
}

describe("defaultModelId", () => {
  it("returns the default when it's offered", () => {
    expect(defaultModelId(settings(["orpheus", "bhashini-indic-parler"], "bhashini-indic-parler"))).toBe(
      "bhashini-indic-parler",
    );
  });

  it("returns the first model when the language-filtered list drops the default", () => {
    expect(defaultModelId(settings(["orpheus"], "bhashini-indic-parler"))).toBe("orpheus");
  });

  it("returns the default when the catalog lists no models", () => {
    expect(defaultModelId(settings(undefined, "neural"))).toBe("neural");
  });

  it("returns the first model when there's no default", () => {
    expect(defaultModelId(settings(["arcana", "mist"]))).toBe("arcana");
  });

  it("returns empty when there's no model field", () => {
    expect(defaultModelId(null)).toBe("");
  });
});

describe("acceptsCustomValue", () => {
  it.each([
    [{ input_type: "dropdown" as const }, false],
    [{ input_type: "input" as const }, true],
    [{ input_type: "both" as const, allow_custom_input: true }, true],
    [{ input_type: "both" as const }, false],
    [{ input_mode: "options" }, false],
    [{ input_mode: "both" }, true],
  ])("%o -> %s", (field, expected) => {
    expect(acceptsCustomValue(field)).toBe(expected);
  });

  it("treats an unknown field as accepting anything", () => {
    expect(acceptsCustomValue(undefined)).toBe(true);
  });
});
