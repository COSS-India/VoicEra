import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ConversationMessage } from "@pipecat-ai/client-react";
import { BrowserCallSession } from "@/components/call/BrowserCallSession";
import { pipecatTestStore } from "@/test-utils/pipecatMock";

vi.mock("@pipecat-ai/client-react", () => import("@/test-utils/pipecatMock"));

const {
  connectBrowserCall,
  isChromeTranslationAvailable,
  detectTextLanguage,
  isTranslationPairAvailable,
  translateLines,
  translateCallTranscriptViaLlm,
  fetchCallTranscriptText,
} = vi.hoisted(() => ({
  connectBrowserCall: vi.fn(),
  isChromeTranslationAvailable: vi.fn(() => false),
  detectTextLanguage: vi.fn(),
  isTranslationPairAvailable: vi.fn(),
  translateLines: vi.fn(),
  translateCallTranscriptViaLlm: vi.fn(),
  fetchCallTranscriptText: vi.fn().mockResolvedValue("[00:00] user: Hola"),
}));

vi.mock("@/lib/pipecat/createBrowserClient", async () => {
  const { pipecatTestStore } = await import("@/test-utils/pipecatMock");
  return {
    createBrowserPipecatClient: () => {
      const client = pipecatTestStore.createClient() as { disconnect?: () => Promise<void> };
      (client as { disconnect: () => Promise<void> }).disconnect = vi.fn().mockResolvedValue(undefined);
      return client;
    },
    connectBrowserCall,
  };
});

vi.mock("@/lib/chrome-translation", () => ({
  isChromeTranslationAvailable,
  detectTextLanguage,
  isTranslationPairAvailable,
  translateLines,
}));

vi.mock("@/lib/api/calls", () => ({
  translateCallTranscriptViaLlm,
  fetchCallTranscriptText,
}));

function userMessage(content: string, createdAt = new Date().toISOString()): ConversationMessage {
  return {
    role: "user",
    createdAt,
    final: true,
    parts: [{ text: content, needsSeparator: false, final: true, createdAt }],
  };
}

function agentMessage(content: string, createdAt = new Date().toISOString()): ConversationMessage {
  return {
    role: "assistant",
    createdAt,
    final: true,
    parts: [{ text: content, needsSeparator: false, final: true, createdAt }],
  };
}

describe("BrowserCallSession / CallStage — New call remount", () => {
  beforeEach(() => {
    connectBrowserCall.mockReset();
    connectBrowserCall.mockResolvedValue("call-1");
    pipecatTestStore.reset();
  });

  afterEach(() => {
    pipecatTestStore.reset();
  });

  it("starts idle and shows 'Start test call' on first mount (no autoStart)", () => {
    render(<BrowserCallSession orgId="org-1" agentId="agent-1" agentName="Test Agent" />);
    expect(screen.getByText("Ready to call")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start test call" })).toBeInTheDocument();
    expect(connectBrowserCall).not.toHaveBeenCalled();
  });

  it("connects when 'Start test call' is clicked", async () => {
    const user = userEvent.setup();
    render(<BrowserCallSession orgId="org-1" agentId="agent-1" agentName="Test Agent" />);

    await user.click(screen.getByRole("button", { name: "Start test call" }));

    await waitFor(() => expect(connectBrowserCall).toHaveBeenCalledTimes(1));
    expect(connectBrowserCall).toHaveBeenCalledWith(expect.anything(), "org-1", "agent-1");
  });

  it("keeps the transcript/details panel visible after disconnect instead of reverting to idle", async () => {
    const user = userEvent.setup();
    render(<BrowserCallSession orgId="org-1" agentId="agent-1" agentName="Test Agent" />);

    await user.click(screen.getByRole("button", { name: "Start test call" }));
    await waitFor(() => expect(connectBrowserCall).toHaveBeenCalledTimes(1));

    act(() => pipecatTestStore.current().setTransportState("connected"));
    act(() => pipecatTestStore.current().addMessage(agentMessage("Hello, how can I help?")));

    expect(screen.getByText(/Hello, how can I help?/)).toBeInTheDocument();

    act(() => pipecatTestStore.current().disconnect());

    // "Call ended" legitimately appears twice: the status label and the
    // ended-state summary card both show it.
    expect(screen.getAllByText("Call ended").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/Hello, how can I help?/)).toBeInTheDocument();
    expect(screen.queryByText("Ready to call")).not.toBeInTheDocument();
  });

  it("does NOT show 'Call ended' if disconnect fires before ever connecting (e.g. a connect error)", () => {
    render(<BrowserCallSession orgId="org-1" agentId="agent-1" agentName="Test Agent" />);

    // Never transitioned through "connected" — simulates an error path.
    act(() => pipecatTestStore.current().disconnect());

    expect(screen.queryByText("Call ended")).not.toBeInTheDocument();
    expect(screen.getByText("Ready to call")).toBeInTheDocument();
  });

  it("'New call' remounts with a fresh transcript — no leftover messages from the previous call", async () => {
    const user = userEvent.setup();
    render(<BrowserCallSession orgId="org-1" agentId="agent-1" agentName="Test Agent" />);

    await user.click(screen.getByRole("button", { name: "Start test call" }));
    await waitFor(() => expect(connectBrowserCall).toHaveBeenCalledTimes(1));
    const firstCallHandle = pipecatTestStore.current();

    act(() => firstCallHandle.setTransportState("connected"));
    act(() => firstCallHandle.addMessage(agentMessage("First call greeting")));
    act(() => firstCallHandle.disconnect());

    expect(screen.getByText(/First call greeting/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "New call" }));

    // The real assertion: "New call" must have produced a genuinely NEW
    // client (createBrowserPipecatClient called again), whose conversation
    // state starts empty on its own — not a manual reset in this test. This
    // is what the mock's per-client-object scoping in pipecatMock.tsx makes
    // possible to verify honestly, matching how a real remount gets a fresh
    // PipecatClient in production.
    await waitFor(() => expect(connectBrowserCall).toHaveBeenCalledTimes(2), { timeout: 2000 });
    const secondCallHandle = pipecatTestStore.current();
    expect(secondCallHandle).not.toBe(firstCallHandle);
    expect(secondCallHandle.getSnapshot().messages).toHaveLength(0);
    expect(screen.queryByText(/First call greeting/)).not.toBeInTheDocument();
  });

  it("'New call' auto-starts the new session (autoStart=true) without a manual click", async () => {
    const user = userEvent.setup();
    render(<BrowserCallSession orgId="org-1" agentId="agent-1" agentName="Test Agent" />);

    await user.click(screen.getByRole("button", { name: "Start test call" }));
    await waitFor(() => expect(connectBrowserCall).toHaveBeenCalledTimes(1));
    act(() => pipecatTestStore.current().setTransportState("connected"));
    act(() => pipecatTestStore.current().disconnect());

    await user.click(screen.getByRole("button", { name: "New call" }));

    // No "Start test call" button to click this time — it should show the
    // auto-starting state and call connectBrowserCall again on its own.
    expect(screen.getByText("Starting new call…")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start test call" })).not.toBeInTheDocument();

    await waitFor(() => expect(connectBrowserCall).toHaveBeenCalledTimes(2), { timeout: 2000 });
  });

  it("shows a connect error and falls back to a manual retry button if auto-start fails", async () => {
    const user = userEvent.setup();
    connectBrowserCall.mockResolvedValueOnce("call-1").mockRejectedValueOnce(new Error("network down"));

    render(<BrowserCallSession orgId="org-1" agentId="agent-1" agentName="Test Agent" />);
    await user.click(screen.getByRole("button", { name: "Start test call" }));
    await waitFor(() => expect(connectBrowserCall).toHaveBeenCalledTimes(1));
    act(() => pipecatTestStore.current().setTransportState("connected"));
    act(() => pipecatTestStore.current().disconnect());

    await user.click(screen.getByRole("button", { name: "New call" }));
    await waitFor(() => expect(connectBrowserCall).toHaveBeenCalledTimes(2), { timeout: 2000 });

    await waitFor(() => expect(screen.getAllByText("network down").length).toBeGreaterThanOrEqual(1));
    expect(screen.getByRole("button", { name: "Start test call" })).toBeInTheDocument();
  });
});

describe("CallStage — Zoom dialog", () => {
  beforeEach(() => {
    connectBrowserCall.mockReset();
    connectBrowserCall.mockResolvedValue("call-1");
    pipecatTestStore.reset();
  });

  it("does not show a Zoom button when there is no transcript yet", async () => {
    const user = userEvent.setup();
    render(<BrowserCallSession orgId="org-1" agentId="agent-1" agentName="Test Agent" />);
    await user.click(screen.getByRole("button", { name: "Start test call" }));
    await waitFor(() => expect(connectBrowserCall).toHaveBeenCalledTimes(1));
    act(() => pipecatTestStore.current().setTransportState("connected"));

    expect(screen.queryByRole("button", { name: "Zoom in on transcript" })).not.toBeInTheDocument();
  });

  it("shows a Zoom button once a transcript exists, even while the call is still live", async () => {
    const user = userEvent.setup();
    render(<BrowserCallSession orgId="org-1" agentId="agent-1" agentName="Test Agent" />);
    await user.click(screen.getByRole("button", { name: "Start test call" }));
    await waitFor(() => expect(connectBrowserCall).toHaveBeenCalledTimes(1));
    act(() => pipecatTestStore.current().setTransportState("connected"));
    act(() => pipecatTestStore.current().addMessage(agentMessage("Hi there")));

    expect(screen.getByRole("button", { name: "Zoom in on transcript" })).toBeInTheDocument();
    // Translate is gated on hasEnded — must not appear mid-call.
    expect(screen.queryByRole("button", { name: /translate/i })).not.toBeInTheDocument();
  });

  it("opens a dialog showing the same transcript content, and closes via the X button", async () => {
    const user = userEvent.setup();
    render(<BrowserCallSession orgId="org-1" agentId="agent-1" agentName="Test Agent" />);
    await user.click(screen.getByRole("button", { name: "Start test call" }));
    await waitFor(() => expect(connectBrowserCall).toHaveBeenCalledTimes(1));
    act(() => pipecatTestStore.current().setTransportState("connected"));
    act(() => pipecatTestStore.current().addMessage(agentMessage("Zoomable content")));

    await user.click(screen.getByRole("button", { name: "Zoom in on transcript" }));

    expect(screen.getByText("Test Agent — transcript")).toBeInTheDocument();
    // Content appears twice now (compact view + zoomed dialog).
    expect(screen.getAllByText(/Zoomable content/).length).toBeGreaterThanOrEqual(2);

    await user.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByText("Test Agent — transcript")).not.toBeInTheDocument();
  });

  it("shows a Translate button inside the zoom dialog only when the call has ended", async () => {
    const user = userEvent.setup();
    render(<BrowserCallSession orgId="org-1" agentId="agent-1" agentName="Test Agent" />);
    await user.click(screen.getByRole("button", { name: "Start test call" }));
    await waitFor(() => expect(connectBrowserCall).toHaveBeenCalledTimes(1));
    act(() => pipecatTestStore.current().setTransportState("connected"));
    act(() => pipecatTestStore.current().addMessage(agentMessage("Line one")));

    await user.click(screen.getByRole("button", { name: "Zoom in on transcript" }));
    expect(screen.queryByRole("button", { name: /^translate$/i })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close" }));
    act(() => pipecatTestStore.current().disconnect());

    await user.click(screen.getByRole("button", { name: "Zoom in on transcript" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("button", { name: /^translate$/i })).toBeInTheDocument();
  });
});

describe("CallStage — Translate", () => {
  beforeEach(() => {
    connectBrowserCall.mockReset();
    connectBrowserCall.mockResolvedValue("call-1");
    isChromeTranslationAvailable.mockReset().mockReturnValue(false);
    detectTextLanguage.mockReset();
    isTranslationPairAvailable.mockReset();
    translateLines.mockReset();
    translateCallTranscriptViaLlm.mockReset();
    fetchCallTranscriptText.mockReset().mockResolvedValue("[00:00] user: Hola");
    pipecatTestStore.reset();
  });

  async function endedCallWithTranscript() {
    const user = userEvent.setup();
    render(<BrowserCallSession orgId="org-1" agentId="agent-1" agentName="Test Agent" />);
    await user.click(screen.getByRole("button", { name: "Start test call" }));
    await waitFor(() => expect(connectBrowserCall).toHaveBeenCalledTimes(1));
    act(() => pipecatTestStore.current().setTransportState("connected"));
    act(() => pipecatTestStore.current().addMessage(userMessage("Hola")));
    act(() => pipecatTestStore.current().disconnect());
    return user;
  }

  it("is disabled until the call has ended", async () => {
    render(<BrowserCallSession orgId="org-1" agentId="agent-1" agentName="Test Agent" />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Start test call" }));
    await waitFor(() => expect(connectBrowserCall).toHaveBeenCalledTimes(1));
    act(() => pipecatTestStore.current().setTransportState("connected"));
    act(() => pipecatTestStore.current().addMessage(userMessage("Hola")));

    expect(screen.queryByRole("button", { name: /^translate$/i })).not.toBeInTheDocument();
  });

  it("shows a translated transcript via the on-device path when available", async () => {
    isChromeTranslationAvailable.mockReturnValue(true);
    detectTextLanguage.mockResolvedValue({ language: "es", confidence: 0.9 });
    isTranslationPairAvailable.mockResolvedValue(true);
    translateLines.mockResolvedValue(["Hello"]);

    const user = await endedCallWithTranscript();
    await user.click(screen.getByRole("button", { name: /^translate$/i }));

    await waitFor(() => expect(screen.getByText(/Hello/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Show original" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Show original" }));
    expect(screen.getByText(/Hola/)).toBeInTheDocument();
  });

  it("falls back to the backend LLM path when on-device translation is unavailable", async () => {
    isChromeTranslationAvailable.mockReturnValue(false);
    translateCallTranscriptViaLlm.mockResolvedValue({
      translated_text: "[00:00] user: Hello",
      target_lang: "en",
      source_lang: "es",
    });

    const user = await endedCallWithTranscript();
    await user.click(screen.getByRole("button", { name: /^translate$/i }));

    await waitFor(() =>
      expect(translateCallTranscriptViaLlm).toHaveBeenCalledWith("call-1", expect.any(String)),
    );
    await waitFor(() => expect(screen.getByText(/Hello/)).toBeInTheDocument());
  });

  it("shows a clear error when the backend transcript isn't saved yet (404 race)", async () => {
    const { ApiError } = await import("@/lib/api/http");
    isChromeTranslationAvailable.mockReturnValue(false);
    translateCallTranscriptViaLlm.mockRejectedValue(new ApiError("Not found", 404));

    const user = await endedCallWithTranscript();
    await user.click(screen.getByRole("button", { name: /^translate$/i }));

    await waitFor(() =>
      expect(screen.getByText(/still being saved/i)).toBeInTheDocument(),
    );
  });

  it("does not fetch the persisted transcript on the free on-device path", async () => {
    isChromeTranslationAvailable.mockReturnValue(true);
    detectTextLanguage.mockResolvedValue({ language: "es", confidence: 0.9 });
    isTranslationPairAvailable.mockResolvedValue(true);
    translateLines.mockResolvedValue(["Hello"]);

    const user = await endedCallWithTranscript();
    await user.click(screen.getByRole("button", { name: /^translate$/i }));

    await waitFor(() => expect(screen.getByText(/Hello/)).toBeInTheDocument());
    expect(fetchCallTranscriptText).not.toHaveBeenCalled();
  });

  it("surfaces the still-being-saved error when the transcript fetch itself 404s", async () => {
    const { ApiError } = await import("@/lib/api/http");
    isChromeTranslationAvailable.mockReturnValue(false);
    translateCallTranscriptViaLlm.mockResolvedValue({
      translated_text: "[00:00] user: Hello",
      target_lang: "en",
      source_lang: "es",
    });
    fetchCallTranscriptText.mockRejectedValue(new ApiError("Not found", 404));

    const user = await endedCallWithTranscript();
    await user.click(screen.getByRole("button", { name: /^translate$/i }));

    await waitFor(() => expect(screen.getByText(/still being saved/i)).toBeInTheDocument());
  });

  it("shows a corrupted-format error when the LLM response has no parseable lines", async () => {
    isChromeTranslationAvailable.mockReturnValue(false);
    translateCallTranscriptViaLlm.mockResolvedValue({
      translated_text: "not a parseable transcript at all",
      target_lang: "en",
      source_lang: "es",
    });

    const user = await endedCallWithTranscript();
    await user.click(screen.getByRole("button", { name: /^translate$/i }));

    await waitFor(() => expect(screen.getByText(/corrupted the transcript format/i)).toBeInTheDocument());
  });

  it("invalidates an in-flight translate when a new call starts before it resolves", async () => {
    isChromeTranslationAvailable.mockReturnValue(false);
    let resolveTranslate: (v: { translated_text: string; target_lang: string; source_lang: string }) => void;
    translateCallTranscriptViaLlm.mockReturnValue(
      new Promise((resolve) => {
        resolveTranslate = resolve;
      }),
    );

    const user = await endedCallWithTranscript();
    await user.click(screen.getByRole("button", { name: /^translate$/i }));
    expect(screen.getByText("Translating…")).toBeInTheDocument();

    // Start a new call before the translate promise resolves.
    await user.click(screen.getByRole("button", { name: "New call" }));

    // Now resolve the stale translate — it must not apply to the new session.
    act(() => {
      resolveTranslate({ translated_text: "[00:00] user: stale result", target_lang: "en", source_lang: "es" });
    });

    await waitFor(() => {
      expect(screen.queryByText(/stale result/)).not.toBeInTheDocument();
    });
  });
});
