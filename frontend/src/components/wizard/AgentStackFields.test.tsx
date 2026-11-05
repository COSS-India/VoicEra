import { render, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { AgentStackFields, type StackFieldsValue } from "@/components/wizard/AgentStackFields";
import type { ProviderSettingsCatalog } from "@/lib/catalog-types";
import type { WizardCatalogs } from "@/lib/use-wizard-catalogs";

// framer-motion's animations reject with AbortError under happy-dom; render plain sections.
vi.mock("framer-motion", () => ({
  motion: {
    section: (props: Record<string, unknown>) => {
      const rest = Object.fromEntries(
        Object.entries(props).filter(([k]) => !["custom", "initial", "animate", "variants"].includes(k)),
      );
      return <section {...rest} />;
    },
  },
}));

vi.mock("@/lib/api-client", () => ({
  ApiError: class ApiError extends Error {},
  previewTts: vi.fn(),
  getPreviewLimits: vi.fn(() => new Promise(() => {})),
}));

function ttsSettings(provider: string, models: string[], defaultModel?: string): ProviderSettingsCatalog {
  return {
    provider,
    name: provider,
    fields: { model: { type: "string", default: defaultModel, examples: models } },
  };
}

function catalogsWith(tts: ProviderSettingsCatalog | null): WizardCatalogs {
  return {
    languages: { en: "English" },
    availableLanguages: { en: "English" },
    languagesLoading: false,
    sttProviders: {},
    ttsProviders: {},
    llmProviders: {},
    telephonyProviders: {},
    sttSettings: null,
    ttsSettings: tts,
    llmSettings: null,
    loading: false,
    error: "",
  };
}

const BASE: StackFieldsValue = {
  langs: ["en"],
  sttProvider: "",
  sttModel: "",
  sttExtra: {},
  ttsProvider: "bhashini",
  ttsModel: "",
  ttsExtra: {},
  llmProvider: "",
  llmModel: "",
  llmExtra: {},
  voice: "",
};

/** Holds the form like the create/edit pages do; `latest` exposes it to assertions. */
function renderStack(catalogs: WizardCatalogs, initial: Partial<StackFieldsValue> = {}) {
  const latest = { current: { ...BASE, ...initial } };
  function Harness() {
    const [value, setValue] = useState<StackFieldsValue>(latest.current);
    latest.current = value;
    return (
      <AgentStackFields
        value={value}
        catalogs={catalogs}
        sections={["tts"]}
        onChange={(key, v) => setValue((f) => ({ ...f, [key]: v }))}
      />
    );
  }
  render(<Harness />);
  return latest;
}

/** The trigger button of the TTS "Model" select, or null when it isn't rendered. */
function modelButton() {
  const label = [...document.querySelectorAll("label")].find(
    (l) => l.firstChild?.nodeType === Node.TEXT_NODE && l.firstChild.textContent?.trim() === "Model",
  );
  return label ? within(label).getByRole("button") : null;
}

describe("AgentStackFields TTS model sync", () => {
  it("selects the provider's default model when none is set", async () => {
    const form = renderStack(catalogsWith(ttsSettings("openai", ["gpt-4o-mini-tts"], "gpt-4o-mini-tts")));
    await waitFor(() => expect(form.current.ttsModel).toBe("gpt-4o-mini-tts"));
    expect(modelButton()).toHaveTextContent("gpt-4o-mini-tts");
  });

  it("replaces another provider's model with this provider's default", async () => {
    const form = renderStack(
      catalogsWith(ttsSettings("bhashini", ["orpheus", "bhashini-indic-parler"], "bhashini-indic-parler")),
      { ttsModel: "bulbul:v3" },
    );
    await waitFor(() => expect(form.current.ttsModel).toBe("bhashini-indic-parler"));
    expect(modelButton()).toHaveTextContent("bhashini-indic-parler");
  });

  it("falls back to the first model when the default isn't listed for the language", async () => {
    // Bhashini + English: the backend keeps default=parler but only lists orpheus.
    const form = renderStack(catalogsWith(ttsSettings("bhashini", ["orpheus"], "bhashini-indic-parler")), {
      ttsModel: "bulbul:v3",
    });
    await waitFor(() => expect(form.current.ttsModel).toBe("orpheus"));
    expect(modelButton()).not.toHaveTextContent("Select…");
  });

  it("falls back to the first model when the catalog has no default", async () => {
    const form = renderStack(catalogsWith(ttsSettings("rime", ["arcana", "mist"])));
    await waitFor(() => expect(form.current.ttsModel).toBe("arcana"));
  });

  it("keeps a saved model that is still listed", async () => {
    const form = renderStack(
      catalogsWith(
        ttsSettings("elevenlabs", ["eleven_flash_v2_5", "eleven_multilingual_v2"], "eleven_flash_v2_5"),
      ),
      { ttsModel: "eleven_multilingual_v2" },
    );
    await new Promise((r) => setTimeout(r, 20));
    expect(form.current.ttsModel).toBe("eleven_multilingual_v2");
    expect(modelButton()).toHaveTextContent("eleven_multilingual_v2");
  });

  it("leaves the model alone while settings are still loading", async () => {
    const form = renderStack(catalogsWith(null), { ttsModel: "bulbul:v3" });
    await new Promise((r) => setTimeout(r, 20));
    expect(form.current.ttsModel).toBe("bulbul:v3");
    expect(modelButton()).toBeNull();
  });
});
