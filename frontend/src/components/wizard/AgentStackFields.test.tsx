import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { AgentStackFields, type StackFieldsValue } from "@/components/wizard/AgentStackFields";
import type { CatalogField, ProviderSettingsCatalog } from "@/lib/catalog-types";
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

function ttsSettings(
  provider: string,
  models: string[],
  defaultModel?: string,
  voice?: CatalogField,
): ProviderSettingsCatalog {
  return {
    provider,
    name: provider,
    fields: {
      model: { type: "string", default: defaultModel, examples: models },
      ...(voice ? { voice } : {}),
    },
  };
}

/** Sarvam-like: a voice list that also accepts custom voice ids. */
const SARVAM = ttsSettings("sarvam", ["bulbul:v3"], "bulbul:v3", {
  type: "string",
  default: "shubh",
  examples: ["anushka", "shubh"],
  input_type: "both",
  allow_custom_input: true,
});

/** Bhashini (Hindi): list-only models and voices, and each model has its own voices. */
const BHASHINI_HI: ProviderSettingsCatalog = {
  provider: "bhashini",
  name: "bhashini",
  fields: {
    model: {
      type: "string",
      default: "bhashini-indic-parler",
      input_mode: "options",
      examples: ["bhashini-indic-parler", "orpheus"],
    },
    voice: { type: "string", input_mode: "input" },
  },
  capabilities: {
    "bhashini-indic-parler": {
      languages: { hi: "hi" },
      settings: { hi: { voice: { default: "Rohit", options: ["Rohit", "Divya"], input_type: "dropdown" } } },
    },
    orpheus: {
      languages: { hi: "hi" },
      settings: { hi: { voice: { default: "Kavya", options: ["Kavya", "Amit"], input_type: "dropdown" } } },
    },
  },
};

/** A provider with two models whose voices accept custom ids. */
const CUSTOM_VOICES = ttsSettings("acme", ["v1", "v2"], "v1", {
  type: "string",
  default: "stock",
  examples: ["stock"],
  input_type: "both",
  allow_custom_input: true,
});

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
    langsChanged: false,
  };
}

const BASE: StackFieldsValue = {
  langs: ["en"],
  sttProvider: "",
  sttModel: "",
  sttExtra: {},
  ttsProvider: "",
  ttsModel: "",
  ttsExtra: {},
  llmProvider: "",
  llmModel: "",
  llmExtra: {},
  voice: "",
};

/** Holds the form like the create/edit pages do; `latest` exposes it to assertions.
 * The form's provider defaults to the catalog's, as it is once that catalog has loaded. */
function renderStack(catalogs: WizardCatalogs, initial: Partial<StackFieldsValue> = {}) {
  const latest = {
    current: { ...BASE, ttsProvider: catalogs.ttsSettings?.provider ?? "", ...initial },
  };
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

/** The trigger button of the labelled field ("Model", "Voice"), or null when it isn't rendered. */
function fieldButton(name: string) {
  const label = [...document.querySelectorAll("label")].find(
    (l) => l.firstChild?.nodeType === Node.TEXT_NODE && l.firstChild.textContent?.trim() === name,
  );
  return label ? within(label).getByRole("button") : null;
}
const modelButton = () => fieldButton("Model");

async function chooseModel(model: string) {
  await userEvent.click(modelButton()!);
  await userEvent.click(await screen.findByRole("option", { name: model }));
}

describe("AgentStackFields TTS model fill", () => {
  it("fills an empty model with the provider's default", async () => {
    const form = renderStack(catalogsWith(ttsSettings("openai", ["gpt-4o-mini-tts"], "gpt-4o-mini-tts")));
    await waitFor(() => expect(form.current.ttsModel).toBe("gpt-4o-mini-tts"));
    expect(modelButton()).toHaveTextContent("gpt-4o-mini-tts");
  });

  it("fills the first model when the default isn't offered for the language", async () => {
    // Bhashini + English: the backend keeps default=parler but only lists orpheus.
    const form = renderStack(catalogsWith(ttsSettings("bhashini", ["orpheus"], "bhashini-indic-parler")));
    await waitFor(() => expect(form.current.ttsModel).toBe("orpheus"));
    expect(modelButton()).toHaveTextContent("orpheus");
  });

  it("fills the first model when the catalog has no default", async () => {
    const form = renderStack(catalogsWith(ttsSettings("rime", ["arcana", "mist"])));
    await waitFor(() => expect(form.current.ttsModel).toBe("arcana"));
    expect(modelButton()).toHaveTextContent("arcana");
  });

  it("keeps a saved model that is listed", async () => {
    const form = renderStack(
      catalogsWith(
        ttsSettings("elevenlabs", ["eleven_flash_v2_5", "eleven_multilingual_v2"], "eleven_flash_v2_5"),
      ),
      { ttsModel: "eleven_multilingual_v2" },
    );
    await act(async () => {});
    expect(form.current.ttsModel).toBe("eleven_multilingual_v2");
  });

  it("keeps a saved model that isn't listed (edit page must not rewrite it)", async () => {
    const form = renderStack(catalogsWith(SARVAM), { ttsModel: "bulbul:v2", voice: "anushka" });
    await act(async () => {});
    expect(form.current.ttsModel).toBe("bulbul:v2");
    expect(form.current.voice).toBe("anushka");
  });

  it("doesn't fill from another provider's catalog", async () => {
    // Just after a provider switch the previous provider's catalog is still loaded.
    const form = renderStack(catalogsWith(SARVAM), { ttsProvider: "bhashini" });
    await act(async () => {});
    expect(form.current.ttsModel).toBe("");
    expect(form.current.voice).toBe("");
  });

  it("leaves the model alone while settings are still loading", async () => {
    const form = renderStack(catalogsWith(null), { ttsProvider: "sarvam", ttsModel: "bulbul:v3" });
    await act(async () => {});
    expect(form.current.ttsModel).toBe("bulbul:v3");
    expect(modelButton()).toBeNull();
  });
});

describe("AgentStackFields TTS voice fill", () => {
  it("fills an empty voice with the catalog default, not the first voice", async () => {
    const form = renderStack(catalogsWith(SARVAM));
    await waitFor(() => expect(form.current.voice).toBe("shubh"));
  });

  it("keeps a saved custom voice", async () => {
    const form = renderStack(catalogsWith(SARVAM), { ttsModel: "bulbul:v3", voice: "my-cloned-voice" });
    await act(async () => {});
    expect(form.current.voice).toBe("my-cloned-voice");
  });

  it("doesn't fill a voice for a model the catalog doesn't list", async () => {
    const form = renderStack(catalogsWith(SARVAM), { ttsModel: "bulbul:v2" });
    await act(async () => {});
    expect(form.current.voice).toBe("");
  });
});

describe("AgentStackFields TTS model change", () => {
  it("replaces a list-only voice the new model doesn't offer", async () => {
    const form = renderStack(catalogsWith(BHASHINI_HI), {
      langs: ["hi"],
      ttsModel: "bhashini-indic-parler",
      voice: "Rohit",
    });
    await chooseModel("orpheus");
    await waitFor(() => expect(form.current.voice).toBe("Kavya"));
    expect(form.current.ttsModel).toBe("orpheus");
  });

  it("keeps a custom voice when the voice field accepts custom ids", async () => {
    const form = renderStack(catalogsWith(CUSTOM_VOICES), { ttsModel: "v1", voice: "my-cloned-voice" });
    await chooseModel("v2");
    await act(async () => {});
    expect(form.current.voice).toBe("my-cloned-voice");
  });
});
