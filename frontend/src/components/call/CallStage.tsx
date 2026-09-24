"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Languages, Maximize2, Mic, MicOff, PhoneOff, X } from "lucide-react";
import { RTVIEvent, type RTVIMessage } from "@pipecat-ai/client-js";
import {
  PipecatClientAudio,
  PipecatClientProvider,
  VoiceVisualizer,
  usePipecatClient,
  usePipecatClientMediaDevices,
  usePipecatClientMicControl,
  usePipecatClientTransportState,
  usePipecatConversation,
  useRTVIClientEvent,
  type BotOutputText,
  type ConversationMessage,
  type ConversationMessagePart,
} from "@pipecat-ai/client-react";
import { Button } from "@/components/ui/Button";
import { Dialog } from "@/components/ui/Dialog";
import { Spinner } from "@/components/ui/Spinner";
import { ApiError } from "@/lib/api/http";
import { translateCallTranscriptViaLlm } from "@/lib/api/calls";
import {
  detectTextLanguage,
  isChromeTranslationAvailable,
  isTranslationPairAvailable,
  translateLines,
} from "@/lib/chrome-translation";
import { connectBrowserCall, createBrowserPipecatClient } from "@/lib/pipecat/createBrowserClient";
import { parseTranscript } from "@/lib/transcript";

function formatDuration(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function isBotOutputText(text: ConversationMessagePart["text"]): text is BotOutputText {
  return typeof text === "object" && text !== null && "spoken" in text && "unspoken" in text;
}

function renderMessageParts(parts: ConversationMessagePart[]): ReactNode {
  return parts.map((part, i) => {
    const key = `${part.createdAt}-${i}`;
    const sep = part.needsSeparator ? " " : "";
    if (typeof part.text === "string") {
      return (
        <span key={key}>
          {sep}
          {part.text}
        </span>
      );
    }
    if (isBotOutputText(part.text)) {
      return (
        <span key={key}>
          {sep}
          <span>{part.text.spoken}</span>
          {part.text.unspoken ? <span className="opacity-50">{part.text.unspoken}</span> : null}
        </span>
      );
    }
    return (
      <span key={key}>
        {sep}
        {part.text}
      </span>
    );
  });
}

export function messageToPlainText(parts: ConversationMessagePart[]): string {
  return parts
    .map((part) => {
      const sep = part.needsSeparator ? " " : "";
      if (typeof part.text === "string") return sep + part.text;
      if (isBotOutputText(part.text)) return sep + part.text.spoken + (part.text.unspoken ?? "");
      return "";
    })
    .join("");
}

// Only these two roles are shown in the transcript panel — filters out
// tool/function-call and system messages.
const TRANSCRIPT_ROLES = new Set(["user", "assistant"]);

function roleLabel(role: string): string {
  if (role === "assistant") return "Agent:";
  if (role === "user") return "User:";
  if (role === "function_call") return "Tool:";
  return "System:";
}

type CallUiState = "idle" | "listening" | "speaking";

interface TranslatedLine {
  role: string;
  content: string;
}

interface Translation {
  lines: TranslatedLine[];
  lang: string;
}

interface TranslateState {
  callId: string | undefined;
  result: Translation | null;
  loading: boolean;
  error: string;
  showing: boolean;
}

const INITIAL_TRANSLATE_STATE: TranslateState = {
  callId: undefined,
  result: null,
  loading: false,
  error: "",
  showing: false,
};

/** Shared transcript rendering — used by both the compact inline panel and
 * the zoomed dialog, so they can never drift into showing different content. */
function TranscriptList({
  messages,
  translation,
  textClassName,
}: {
  messages: ConversationMessage[];
  translation: Translation | null;
  textClassName: string;
}) {
  if (translation) {
    return (
      <>
        {translation.lines.map((l, i) => (
          <p key={i} className={textClassName}>
            <span className="font-semibold text-white/60">{l.role}</span> {l.content}
          </p>
        ))}
      </>
    );
  }
  return (
    <>
      {messages.map((m, i) => (
        <p
          key={`${m.createdAt}-${m.role}-${i}`}
          className={`${textClassName} ${m.final === false ? "opacity-70" : ""}`}
        >
          <span className="font-semibold text-white/60">{roleLabel(m.role)}</span>{" "}
          {renderMessageParts(m.parts)}
        </p>
      ))}
    </>
  );
}

/**
 * Video-call-style stage built on Pipecat React primitives. Shared by the
 * dashboard test modal and the wizard Review step (both via
 * BrowserCallSession, which owns the PipecatClientProvider and the remount
 * key `onRequestNewSession` triggers).
 */
function CallStage({
  orgId,
  agentId,
  agentName,
  autoStart,
  onRequestNewSession,
}: {
  orgId: string;
  agentId: string;
  agentName: string;
  /** Immediately starts a call on mount — used for the fresh instance a
   * "New call" click remounts, so the user doesn't have to click "Start
   * test call" again. */
  autoStart: boolean;
  onRequestNewSession: () => void;
}) {
  const client = usePipecatClient();
  const transportState = usePipecatClientTransportState();
  const { enableMic } = usePipecatClientMicControl();
  const { availableMics, selectedMic, updateMic } = usePipecatClientMediaDevices();
  const { messages } = usePipecatConversation();
  const transcriptRef = useRef<HTMLDivElement>(null);
  const userStoppedAtRef = useRef<number | null>(null);
  // Tracks whether the current session ever reached "connected", so a call
  // that errors out before connecting doesn't get treated as "ended" (which
  // would hide the connect error behind the ended-call summary view).
  const connectedOnceRef = useRef(false);
  // Monotonic guard: invalidates an in-flight translate request when the
  // user starts a new call before it resolves.
  const translateRequestId = useRef(0);

  const [seconds, setSeconds] = useState(0);
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState("");
  const [botSpeaking, setBotSpeaking] = useState(false);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  // Optimistic mic UI — Pipecat's React mic flag starts false and can drift
  // with the WS media manager; keep local state in sync with enableMic().
  const [micEnabled, setMicEnabled] = useState(true);
  // Sticky: set once a connected call disconnects; only cleared by starting
  // a new call. Keeps the transcript/details panel visible post-disconnect
  // instead of reverting to the idle "Start test call" screen.
  const [hasEnded, setHasEnded] = useState(false);
  const [translate, setTranslate] = useState<TranslateState>(INITIAL_TRANSLATE_STATE);
  const [zoomed, setZoomed] = useState(false);
  const zoomedTranscriptRef = useRef<HTMLDivElement>(null);

  const isLive =
    transportState === "connecting" ||
    transportState === "connected" ||
    transportState === "ready" ||
    connecting;

  const isConnected = transportState === "ready" || transportState === "connected";
  const showDetails = isLive || hasEnded;
  const targetLang = (navigator.language || "en").split("-")[0]!;

  useEffect(() => {
    if (!isConnected) return;
    connectedOnceRef.current = true;
    const id = window.setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => window.clearInterval(id);
  }, [isConnected]);

  useEffect(() => {
    const panel = transcriptRef.current;
    if (!panel) return;
    requestAnimationFrame(() => {
      panel.scrollTop = panel.scrollHeight;
    });
  }, [messages]);

  useEffect(() => {
    if (!zoomed) return;
    const panel = zoomedTranscriptRef.current;
    if (!panel) return;
    requestAnimationFrame(() => {
      panel.scrollTop = panel.scrollHeight;
    });
  }, [zoomed, messages]);

  useRTVIClientEvent(
    RTVIEvent.UserStoppedSpeaking,
    useCallback(() => {
      userStoppedAtRef.current = performance.now();
    }, []),
  );

  useRTVIClientEvent(
    RTVIEvent.BotStartedSpeaking,
    useCallback(() => {
      setBotSpeaking(true);
      const started = userStoppedAtRef.current;
      if (started != null) {
        setLatencyMs(Math.round(performance.now() - started));
        userStoppedAtRef.current = null;
      }
    }, []),
  );

  useRTVIClientEvent(
    RTVIEvent.BotStoppedSpeaking,
    useCallback(() => {
      setBotSpeaking(false);
    }, []),
  );

  useRTVIClientEvent(
    RTVIEvent.Disconnected,
    useCallback(() => {
      setConnecting(false);
      setBotSpeaking(false);
      setMicEnabled(true);
      userStoppedAtRef.current = null;
      // Leave seconds/latencyMs alone — they become the ended-call summary.
      if (connectedOnceRef.current) setHasEnded(true);
    }, []),
  );

  useRTVIClientEvent(
    RTVIEvent.Error,
    useCallback((msg: RTVIMessage) => {
      const data = msg.data as { message?: string } | undefined;
      setConnectError(data?.message || "Call error");
      setConnecting(false);
    }, []),
  );

  const startCall = useCallback(async () => {
    if (!client || !orgId || !agentId) return;
    setConnectError("");
    setConnecting(true);
    setSeconds(0);
    setLatencyMs(null);
    setMicEnabled(true);
    connectedOnceRef.current = false;
    setHasEnded(false);
    // Invalidate any in-flight translate from the previous call before it
    // can resolve into this one's state.
    translateRequestId.current += 1;
    setTranslate(INITIAL_TRANSLATE_STATE);
    try {
      const callId = await connectBrowserCall(client, orgId, agentId);
      setTranslate((prev) => ({ ...prev, callId }));
    } catch (err) {
      setConnectError(err instanceof Error ? err.message : "Couldn't start the test call");
      setConnecting(false);
      return;
    }
    setConnecting(false);
  }, [client, orgId, agentId]);

  useEffect(() => {
    if (!autoStart) return;
    // Only ever run once per mount (a fresh `key` from "New call" gives a
    // fresh CallStage instance) — not on every startCall/autoStart identity
    // change, which would re-trigger on unrelated re-renders. startCall is
    // the same imperative action already wired to the "Start test call"
    // button's onClick; this just fires it automatically once instead.
    //
    // The short delay is a mitigation for a runtime-side race: connecting
    // immediately after the previous call's session tears down can produce
    // a duplicated greeting (observed: the agent's opening line spoken/shown
    // twice), most likely because the runtime hasn't fully released the
    // prior call's resources yet. This doesn't fix the underlying race, it
    // just gives teardown a head start.
    const id = window.setTimeout(() => {
      void startCall();
    }, 750);
    return () => window.clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const endCall = useCallback(async () => {
    if (!client) return;
    setConnecting(false);
    setBotSpeaking(false);
    setMicEnabled(true);
    userStoppedAtRef.current = null;
    try {
      await client.disconnect();
    } catch {
      /* ignore */
    }
  }, [client]);

  const toggleMic = useCallback(() => {
    if (!isConnected) return;
    const next = !micEnabled;
    setMicEnabled(next);
    enableMic(next);
  }, [enableMic, isConnected, micEnabled]);

  function getStatusLabel(): string {
    if (connectError) return connectError;
    if (connecting || transportState === "connecting") return "Connecting…";
    if (transportState === "ready" || transportState === "connected") return "Connected";
    if (transportState === "error") return "Error";
    if (hasEnded) return "Call ended";
    return "Ready";
  }
  const statusLabel = getStatusLabel();

  const callState: CallUiState = !isConnected ? "idle" : botSpeaking ? "speaking" : "listening";
  const visibleMessages = messages.filter((m) => TRANSCRIPT_ROLES.has(m.role));
  const hasTranscript = visibleMessages.length > 0;

  const hasCachedTranslation = translate.result !== null && translate.result.lang === targetLang;

  /** Free, on-device path via Chrome's built-in Translator API. Returns null
   * when the API or the requested language pair isn't supported, so the
   * caller can fall back to the backend LLM. */
  async function translateOnDevice(originalMessages: TranslatedLine[]): Promise<Translation | null> {
    if (!isChromeTranslationAvailable()) return null;

    const originals = originalMessages.map((m) => m.content);
    const detected = await detectTextLanguage(originals.join("\n"));
    const sourceLanguage = detected?.language;
    if (!sourceLanguage || !(await isTranslationPairAvailable(sourceLanguage, targetLang))) return null;

    const texts = await translateLines(originals, sourceLanguage, targetLang);
    // Same length/order as originalMessages — safe to zip back by index.
    const lines = originalMessages.map((m, i) => ({ role: m.role, content: texts[i] ?? m.content }));
    return { lines, lang: targetLang };
  }

  /** Backend LLM fallback. Translates the server-persisted transcript, not
   * the client's local message list — the two can have a different number/
   * segmentation of turns, so the result is its own line list rather than
   * zipped index-for-index onto the live messages. */
  async function translateViaBackend(callId: string): Promise<Translation> {
    const response = await translateCallTranscriptViaLlm(callId, targetLang);
    const parsedLines = parseTranscript(response.translated_text);
    if (parsedLines.length === 0) {
      throw new Error("The translation model corrupted the transcript format. Please try again.");
    }
    return {
      lines: parsedLines.map((l) => ({ role: roleLabel(l.role), content: l.content })),
      lang: response.target_lang,
    };
  }

  async function handleTranslate() {
    const originalMessages = visibleMessages.map((m) => ({
      role: roleLabel(m.role),
      content: messageToPlainText(m.parts),
    }));
    if (originalMessages.length === 0) return;

    const myRequest = (translateRequestId.current += 1);
    const isStale = () => translateRequestId.current !== myRequest;
    setTranslate((prev) => ({ ...prev, loading: true, error: "" }));

    try {
      let result = await translateOnDevice(originalMessages);
      if (!result) {
        if (!translate.callId) {
          throw new Error("On-device translation isn't available in this browser for this language.");
        }
        result = await translateViaBackend(translate.callId);
      }
      if (isStale()) return;
      setTranslate((prev) => ({ ...prev, result, showing: true }));
    } catch (err) {
      if (isStale()) return;
      const message =
        err instanceof ApiError && err.status === 404
          ? "Transcript is still being saved — try again in a few seconds."
          : err instanceof Error
            ? err.message
            : "Failed to translate transcript. Please try again.";
      setTranslate((prev) => ({ ...prev, error: message }));
    } finally {
      if (!isStale()) setTranslate((prev) => ({ ...prev, loading: false }));
    }
  }

  function translateButtonLabel(): string {
    if (translate.showing) return "Show original";
    if (hasCachedTranslation) return "Show translation";
    return "Translate";
  }

  function onTranslateButtonClick(): void {
    if (translate.showing) setTranslate((prev) => ({ ...prev, showing: false }));
    else if (hasCachedTranslation) setTranslate((prev) => ({ ...prev, showing: true }));
    else void handleTranslate();
  }

  return (
    <div
      className={`relative flex h-full min-h-[360px] flex-col gap-5 overflow-hidden rounded-v-md border bg-v-fg p-6 text-white transition-colors ${
        hasEnded ? "border-white/20" : "border-v-line"
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-1.5 text-[11px] font-medium text-white/60">
          <span
            className={`size-1.5 rounded-full transition-colors ${
              isConnected ? "bg-emerald-400" : "bg-white/30"
            }`}
          />
          {statusLabel}
        </span>
        {isConnected || hasEnded ? (
          <span className="flex items-center gap-3 font-mono text-[11px] tabular-nums text-white/60">
            {latencyMs != null ? <span>Turn {latencyMs}ms</span> : null}
            <span>{formatDuration(seconds)}</span>
          </span>
        ) : null}
      </div>

      {!showDetails ? (
        <div className="relative flex flex-1 items-center justify-center">
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-20">
            <VoiceVisualizer
              participantType="local"
              backgroundColor="transparent"
              barColor="rgba(255,255,255,0.35)"
              barCount={5}
              barGap={8}
              barWidth={10}
              barMaxHeight={64}
              barOrigin="center"
            />
          </div>
          <div
            key={autoStart && !connectError ? "starting" : "ready"}
            className="animate-v-pop relative flex flex-col items-center gap-4 rounded-v-md border border-white/10 bg-white/5 px-12 py-10 backdrop-blur-md"
          >
            {autoStart && !connectError ? (
              <>
                <Spinner />
                <span className="font-mono text-[11px] uppercase tracking-[.14em] text-white/50">
                  Starting new call…
                </span>
              </>
            ) : (
              <>
                <span className="font-mono text-[11px] uppercase tracking-[.14em] text-white/50">Ready to call</span>
                <Button size="md" disabled={!client || !orgId || !agentId} onClick={() => void startCall()}>
                  Start test call
                </Button>
              </>
            )}
            {connectError ? <span className="max-w-xs text-center text-[12px] text-red-300">{connectError}</span> : null}
          </div>
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-5 sm:grid-cols-[176px_minmax(0,1fr)]">
          <div className="flex flex-col items-center justify-center gap-4">
            {isLive ? (
              <>
                <div
                  className="relative flex h-28 w-28 items-center justify-center"
                  aria-label={callState === "speaking" ? "Agent speaking" : "Listening"}
                >
                  {/*
                    WebSocket transport only exposes a local MediaStreamTrack.
                    Keep local VoiceVisualizer mounted; restyle when the agent speaks.
                  */}
                  <VoiceVisualizer
                    participantType="local"
                    backgroundColor="transparent"
                    barColor={
                      callState === "speaking" ? "rgba(110,231,183,0.95)" : "rgba(255,255,255,0.9)"
                    }
                    barCount={5}
                    barGap={6}
                    barWidth={12}
                    barMaxHeight={96}
                    barOrigin="center"
                  />
                </div>
                <span className="font-mono text-[11px] uppercase tracking-[.14em] text-white/50">
                  {!isConnected
                    ? "Connecting"
                    : callState === "speaking"
                      ? "Agent speaking"
                      : "Listening"}
                </span>

                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    aria-label={micEnabled ? "Mute microphone" : "Unmute microphone"}
                    aria-pressed={!micEnabled}
                    disabled={!isConnected}
                    onClick={toggleMic}
                    className={`flex size-11 cursor-pointer items-center justify-center rounded-full transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
                      !micEnabled
                        ? "bg-white/15 text-white/70 hover:bg-white/25"
                        : "bg-white text-v-fg hover:bg-white/90"
                    }`}
                  >
                    {!micEnabled ? (
                      <MicOff className="size-5" strokeWidth={1.75} />
                    ) : (
                      <Mic className="size-5" strokeWidth={1.75} />
                    )}
                  </button>

                  <button
                    type="button"
                    aria-label="End call"
                    onClick={() => void endCall()}
                    className="flex size-11 cursor-pointer items-center justify-center rounded-full bg-v-danger text-white transition-colors hover:bg-red-600"
                  >
                    <PhoneOff className="size-5" strokeWidth={1.75} />
                  </button>
                </div>

                {isConnected && availableMics.length > 0 ? (
                  <label className="flex w-full max-w-[160px] flex-col gap-1">
                    <span className="font-mono text-[9px] uppercase tracking-[.12em] text-white/40">Mic</span>
                    <select
                      className="w-full truncate rounded-v-sm border border-white/15 bg-white/5 px-2 py-1.5 text-[11px] text-white outline-none"
                      value={selectedMic?.deviceId ?? ""}
                      onChange={(e) => void updateMic(e.target.value)}
                    >
                      {availableMics.map((mic) => (
                        <option key={mic.deviceId} value={mic.deviceId} className="text-v-fg">
                          {mic.label || `Mic ${mic.deviceId.slice(0, 8)}`}
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}
              </>
            ) : (
              <>
                <span className="font-mono text-[11px] uppercase tracking-[.14em] text-white/50">Call ended</span>
                <span className="font-mono text-[13px] tabular-nums text-white/70">
                  {formatDuration(seconds)}
                </span>

                <Button size="sm" onClick={onRequestNewSession}>
                  New call
                </Button>
              </>
            )}
          </div>

          <div className="flex min-h-0 min-w-0 flex-col gap-2">
            {hasEnded || hasTranscript ? (
              <div className="flex items-center justify-end gap-3">
                {hasEnded ? (
                  <button
                    type="button"
                    onClick={onTranslateButtonClick}
                    disabled={translate.loading || !hasTranscript}
                    className="flex cursor-pointer items-center gap-1.5 text-xs font-medium text-white/70 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    {translate.loading ? <Spinner /> : <Languages className="size-3.5" strokeWidth={1.75} />}
                    {translate.loading ? "Translating…" : translateButtonLabel()}
                  </button>
                ) : null}
                {hasTranscript ? (
                  <button
                    type="button"
                    aria-label="Zoom in on transcript"
                    onClick={() => setZoomed(true)}
                    className="flex cursor-pointer items-center gap-1.5 text-xs font-medium text-white/70 hover:text-white"
                  >
                    <Maximize2 className="size-3.5" strokeWidth={1.75} />
                    Zoom
                  </button>
                ) : null}
              </div>
            ) : null}

            {translate.error ? (
              <span className="text-right text-[11px] text-red-300">{translate.error}</span>
            ) : null}

            <div
              ref={transcriptRef}
              className="flex min-h-40 flex-1 max-h-[min(320px,42vh)] flex-col gap-2 overflow-y-scroll overscroll-contain rounded-v-sm bg-white/5 p-4 [scrollbar-color:rgba(255,255,255,0.35)_transparent] [scrollbar-width:thin] [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-white/35 [&::-webkit-scrollbar-track]:bg-transparent"
            >
              {!hasTranscript ? (
                <span className="text-xs text-white/40">
                  Speak after the greeting — the transcript appears here.
                </span>
              ) : null}

              <TranscriptList
                messages={visibleMessages}
                translation={translate.showing ? translate.result : null}
                textClassName="text-[14px] leading-relaxed"
              />
            </div>
          </div>
        </div>
      )}

      <Dialog
        open={zoomed}
        onClose={() => setZoomed(false)}
        widthClassName="max-w-4xl"
        panelClassName="min-h-[70vh] border-0 bg-v-fg text-white"
      >
        <div
          ref={zoomedTranscriptRef}
          className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto overscroll-contain [scrollbar-color:rgba(255,255,255,0.35)_transparent] [scrollbar-width:thin]"
        >
          <div className="sticky top-0 z-10 flex shrink-0 items-center justify-between gap-3 border-b border-white/10 bg-v-fg px-6 py-4">
            <span className="text-[15px] font-semibold">{agentName} — transcript</span>
            <div className="flex items-center gap-3">
              {hasEnded ? (
                <button
                  type="button"
                  onClick={onTranslateButtonClick}
                  disabled={translate.loading || !hasTranscript}
                  className="flex cursor-pointer items-center gap-1.5 text-xs font-medium text-white/70 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {translate.loading ? <Spinner /> : <Languages className="size-3.5" strokeWidth={1.75} />}
                  {translate.loading ? "Translating…" : translateButtonLabel()}
                </button>
              ) : null}
              <button
                type="button"
                aria-label="Close"
                onClick={() => setZoomed(false)}
                className="flex size-8 cursor-pointer items-center justify-center rounded-v-sm text-white/60 transition-colors hover:bg-white/10 hover:text-white"
              >
                <X className="size-4" strokeWidth={1.75} />
              </button>
            </div>
          </div>

          <div className="flex flex-col gap-3 px-6 pb-6">
            {translate.error ? (
              <span className="text-[11px] text-red-300">{translate.error}</span>
            ) : null}

            {!hasTranscript ? (
              <span className="text-sm text-white/40">
                Speak after the greeting — the transcript appears here.
              </span>
            ) : null}

            <TranscriptList
              messages={visibleMessages}
              translation={translate.showing ? translate.result : null}
              textClassName="text-[16px] leading-loose"
            />
          </div>
        </div>
      </Dialog>

      <span className="sr-only" aria-live="polite">
        {agentName} test call {hasEnded ? "has ended" : callState === "idle" ? "is not started" : `is ${callState}`}
      </span>
    </div>
  );
}

/**
 * Owns the Pipecat client + provider for one call session. Remount this
 * (via a changing `key` from the caller — see BrowserCallSession) to get a
 * fully fresh client/transcript for "New call", since Pipecat's own
 * conversation state has no reset API and otherwise persists across
 * connect()/disconnect() on the same client.
 */
export function CallStageSession({
  orgId,
  agentId,
  agentName,
  autoStart,
  onRequestNewSession,
}: {
  orgId: string;
  agentId: string;
  agentName: string;
  autoStart: boolean;
  onRequestNewSession: () => void;
}) {
  const client = useMemo(() => createBrowserPipecatClient(), []);

  useEffect(() => {
    return () => {
      void client.disconnect().catch(() => {});
    };
  }, [client]);

  return (
    <PipecatClientProvider client={client}>
      <PipecatClientAudio />
      <CallStage
        orgId={orgId}
        agentId={agentId}
        agentName={agentName}
        autoStart={autoStart}
        onRequestNewSession={onRequestNewSession}
      />
    </PipecatClientProvider>
  );
}
