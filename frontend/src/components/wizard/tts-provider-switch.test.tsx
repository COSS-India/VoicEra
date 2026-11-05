import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AgentStackFields, type StackFieldsValue } from "@/components/wizard/AgentStackFields";
import type { ProviderSettingsCatalog } from "@/lib/catalog-types";
import { useWizardCatalogs } from "@/lib/use-wizard-catalogs";

// Integration: the real useWizardCatalogs + AgentStackFields wired the way the
// create/edit pages wire them; only the network (api-client) is faked.

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

const { getTtsSettings } = vi.hoisted(() => ({ getTtsSettings: vi.fn() }));

vi.mock("@/lib/api-client", () => ({
  ApiError: class ApiError extends Error {},
  previewTts: vi.fn(),
  getPreviewLimits: vi.fn(() => new Promise(() => {})),
  getLanguages: vi.fn(async () => ({ languages: { en: "English", hi: "Hindi" } })),
  listSttProviders: vi.fn(async () => ({})),
  listLlmProviders: vi.fn(async () => ({})),
  listTelephonyProviders: vi.fn(async () => ({})),
  listTtsProviders: vi.fn(async () => ({
    sarvam: { provider: "sarvam", name: "Sarvam", authenticated: true },
    bhashini: { provider: "bhashini", name: "Bhashini", authenticated: true },
  })),
  getSttSettings: vi.fn(async () => null),
  getLlmSettings: vi.fn(async () => null),
  getTtsSettings,
}));

const SARVAM: ProviderSettingsCatalog = {
  provider: "sarvam",
  name: "Sarvam",
  fields: { model: { type: "string", default: "bulbul:v3", examples: ["bulbul:v3"] } },
};

/** Mirrors the backend: English trims Bhashini to orpheus but keeps default=parler. */
function bhashini(lang: string): ProviderSettingsCatalog {
  const examples = lang === "en" ? ["orpheus"] : ["bhashini-indic-parler", "orpheus"];
  return {
    provider: "bhashini",
    name: "Bhashini",
    fields: { model: { type: "string", default: "bhashini-indic-parler", examples } },
  };
}

/** Settings requests stay pending until the test releases them, to observe the loading window. */
const pending: { provider: string; langs: string[]; resolve: (s: ProviderSettingsCatalog) => void }[] = [];

async function release(provider: string) {
  const i = pending.findIndex((p) => p.provider === provider);
  if (i < 0) throw new Error(`no pending settings request for ${provider}`);
  const [req] = pending.splice(i, 1);
  await act(async () => req!.resolve(provider === "sarvam" ? SARVAM : bhashini(req!.langs[0]!)));
}

function Page({ langs }: { langs: string[] }) {
  const [form, setForm] = useState<StackFieldsValue>({
    langs,
    sttProvider: "",
    sttModel: "",
    sttExtra: {},
    ttsProvider: "sarvam",
    ttsModel: "",
    ttsExtra: {},
    llmProvider: "",
    llmModel: "",
    llmExtra: {},
    voice: "",
  });
  const catalogs = useWizardCatalogs(form.langs, form.sttProvider, form.ttsProvider, form.llmProvider);
  const onChange = <K extends keyof StackFieldsValue>(key: K, value: StackFieldsValue[K]) =>
    setForm((f) => ({ ...f, [key]: value }));
  return (
    <>
      <AgentStackFields value={form} onChange={onChange} catalogs={catalogs} sections={["tts"]} />
      <button type="button" onClick={() => onChange("ttsProvider", "bhashini")}>
        switch-to-bhashini
      </button>
      <output data-testid="tts-model">{form.ttsModel}</output>
    </>
  );
}

function modelButton() {
  const label = [...document.querySelectorAll("label")].find(
    (l) => l.firstChild?.nodeType === Node.TEXT_NODE && l.firstChild.textContent?.trim() === "Model",
  );
  return label ? within(label).getByRole("button") : null;
}

async function startOnSarvam(langs: string[]) {
  render(<Page langs={langs} />);
  await waitFor(() => expect(pending.some((p) => p.provider === "sarvam")).toBe(true));
  await release("sarvam");
  await waitFor(() => expect(modelButton()).toHaveTextContent("bulbul:v3"));
}

describe("TTS provider switch (useWizardCatalogs + AgentStackFields)", () => {
  beforeEach(() => {
    pending.length = 0;
    getTtsSettings.mockReset();
    getTtsSettings.mockImplementation(
      (provider: string, langs: string[]) =>
        new Promise((resolve) => {
          if (langs.length === 0) return resolve(null); // availability probe, not under test
          pending.push({ provider, langs, resolve });
        }),
    );
  });

  it("selects Bhashini's first listed model for English (default not offered)", async () => {
    await startOnSarvam(["en"]);
    await userEvent.click(screen.getByText("switch-to-bhashini"));
    await release("bhashini");
    await waitFor(() => expect(screen.getByTestId("tts-model")).toHaveTextContent("orpheus"));
    expect(modelButton()).toHaveTextContent("orpheus");
  });

  it("selects Bhashini's default model for Hindi", async () => {
    await startOnSarvam(["hi"]);
    await userEvent.click(screen.getByText("switch-to-bhashini"));
    await release("bhashini");
    await waitFor(() => expect(screen.getByTestId("tts-model")).toHaveTextContent("bhashini-indic-parler"));
    expect(modelButton()).toHaveTextContent("bhashini-indic-parler");
  });

  it("never shows the old provider's model list while the new settings load", async () => {
    await startOnSarvam(["en"]);
    await userEvent.click(screen.getByText("switch-to-bhashini"));
    // Bhashini's settings are still in flight: Sarvam's model must not be offered.
    await waitFor(() => expect(modelButton()).toBeNull());
    expect(screen.queryByText("bulbul:v3", { selector: "button *" })).toBeNull();
    await release("bhashini");
    await waitFor(() => expect(modelButton()).toHaveTextContent("orpheus"));
  });
});
