"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Mic, MicOff, PhoneOff } from "lucide-react";
import { RTVIEvent, type RTVIMessage } from "@pipecat-ai/client-js";
import {
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
import { connectBrowserCall } from "@/lib/pipecat/createBrowserClient";

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

function roleLabel(role: ConversationMessage["role"]): string {
  if (role === "assistant") return "Agent:";
  if (role === "user") return "User:";
  if (role === "function_call") return "Tool:";
  return "System:";
}

type CallUiState = "idle" | "listening" | "speaking";

/**
 * Video-call-style stage built on Pipecat React primitives. Shared by the
 * dashboard test modal and the wizard Review step.
 */
export function CallStage({
  orgId,
  agentId,
  agentName,
}: {
  orgId: string;
  agentId: string;
  agentName: string;
}) {
  const client = usePipecatClient();
  const transportState = usePipecatClientTransportState();
  const { enableMic } = usePipecatClientMicControl();
  const { availableMics, selectedMic, updateMic } = usePipecatClientMediaDevices();
  const { messages } = usePipecatConversation();
  const transcriptRef = useRef<HTMLDivElement>(null);
  const userStoppedAtRef = useRef<number | null>(null);

  const [seconds, setSeconds] = useState(0);
  const [connecting, setConnecting] = useState(false);
  const [connectError, setConnectError] = useState("");
  const [botSpeaking, setBotSpeaking] = useState(false);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  // Optimistic mic UI — Pipecat's React mic flag starts false and can drift
  // with the WS media manager; keep local state in sync with enableMic().
  const [micEnabled, setMicEnabled] = useState(true);

  const isLive =
    transportState === "connecting" ||
    transportState === "connected" ||
    transportState === "ready" ||
    connecting;

  const isConnected = transportState === "ready" || transportState === "connected";

  useEffect(() => {
    if (!isConnected) return;
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
      setSeconds(0);
      setLatencyMs(null);
      setMicEnabled(true);
      userStoppedAtRef.current = null;
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
    try {
      await connectBrowserCall(client, orgId, agentId);
    } catch (err) {
      setConnectError(err instanceof Error ? err.message : "Couldn't start the test call");
      setConnecting(false);
      return;
    }
    setConnecting(false);
  }, [client, orgId, agentId]);

  const endCall = useCallback(async () => {
    if (!client) return;
    setConnecting(false);
    setBotSpeaking(false);
    setSeconds(0);
    setLatencyMs(null);
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

  const statusLabel = connectError
    ? connectError
    : connecting || transportState === "connecting"
      ? "Connecting…"
      : transportState === "ready" || transportState === "connected"
        ? "Connected"
        : transportState === "error"
          ? "Error"
          : "Ready";

  const callState: CallUiState = !isConnected ? "idle" : botSpeaking ? "speaking" : "listening";
  const visibleMessages = messages.filter((m) => m.role === "user" || m.role === "assistant");
  const hasTranscript = visibleMessages.length > 0;

  return (
    <div className="relative flex h-full min-h-[360px] flex-col gap-5 overflow-hidden rounded-v-md border border-v-line bg-v-fg p-6 text-white">
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-1.5 text-[11px] font-medium text-white/60">
          <span
            className={`size-1.5 rounded-full transition-colors ${
              isConnected ? "bg-emerald-400" : "bg-white/30"
            }`}
          />
          {statusLabel}
        </span>
        {isConnected ? (
          <span className="flex items-center gap-3 font-mono text-[11px] tabular-nums text-white/60">
            {latencyMs != null ? <span>Turn {latencyMs}ms</span> : null}
            <span>{formatDuration(seconds)}</span>
          </span>
        ) : null}
      </div>

      {!isLive ? (
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
          <div className="relative flex flex-col items-center gap-4 rounded-v-md border border-white/10 bg-white/5 px-12 py-10 backdrop-blur-md">
            <span className="font-mono text-[11px] uppercase tracking-[.14em] text-white/50">Ready to call</span>
            <Button size="md" disabled={!client || !orgId || !agentId} onClick={() => void startCall()}>
              Start test call
            </Button>
            {connectError ? <span className="max-w-xs text-center text-[12px] text-red-300">{connectError}</span> : null}
          </div>
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-5 sm:grid-cols-[176px_minmax(0,1fr)]">
          <div className="flex flex-col items-center justify-center gap-4">
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
          </div>

          <div
            ref={transcriptRef}
            className="flex max-h-[min(320px,42vh)] min-h-40 min-w-0 flex-col gap-2 overflow-y-scroll overscroll-contain rounded-v-sm bg-white/5 p-4 [scrollbar-color:rgba(255,255,255,0.35)_transparent] [scrollbar-width:thin] [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-white/35 [&::-webkit-scrollbar-track]:bg-transparent"
          >
            {!hasTranscript ? (
              <span className="text-xs text-white/40">
                Speak after the greeting — the transcript appears here.
              </span>
            ) : null}

            {visibleMessages.map((m, i) => (
              <p
                key={`${m.createdAt}-${m.role}-${i}`}
                className={`text-[14px] leading-relaxed ${m.final === false ? "opacity-70" : ""}`}
              >
                <span className="font-semibold text-white/60">{roleLabel(m.role)}</span>{" "}
                {renderMessageParts(m.parts)}
              </p>
            ))}
          </div>
        </div>
      )}

      <span className="sr-only" aria-live="polite">
        {agentName} test call is {callState === "idle" ? "not started" : callState}
      </span>
    </div>
  );
}
