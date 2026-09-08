"use client";

import { useEffect, useRef, useState } from "react";
import { Mic, MicOff, PhoneOff } from "lucide-react";
import { Orb } from "orb-ui";
import { Button } from "@/components/ui/Button";
import { usePipecatAudio } from "@/hooks/usePipecatAudio";

function formatDuration(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

type CallState = "idle" | "listening" | "speaking";

/**
 * Video-call-style stage. Idle: a centered "Start test call" button over a
 * blurred backdrop. Connected: avatar + controls on the left, the live
 * transcript on the right. Ending the call (isConnected flips false) drops
 * straight back to the same idle/blurred screen, ready to start again.
 * Shared by the dashboard's "Test call" modal and the agent-creation
 * wizard's Review step, so both give the exact same live-call experience.
 */
export function CallStage({ audio, agentName }: { audio: ReturnType<typeof usePipecatAudio>; agentName: string }) {
  const [seconds, setSeconds] = useState(0);
  const transcriptRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!audio.isConnected) {
      setSeconds(0);
      return;
    }
    const id = window.setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => window.clearInterval(id);
  }, [audio.isConnected]);

  useEffect(() => {
    const panel = transcriptRef.current;
    if (!panel) return;
    // scrollIntoView on the bottom anchor scrolls the modal/page; drive the
    // transcript panel's own scrollTop so new lines stay in view.
    requestAnimationFrame(() => {
      panel.scrollTop = panel.scrollHeight;
    });
  }, [audio.transcriptHistory, audio.liveAssistantText, audio.liveUserText]);

  const callState: CallState = !audio.isConnected ? "idle" : audio.isPlaying ? "speaking" : "listening";
  const hasTranscript = audio.transcriptHistory.length > 0 || Boolean(audio.liveAssistantText) || Boolean(audio.liveUserText);
  // Voice-reactive orb: bar height follows whichever side of the conversation
  // is currently making sound — the agent's output while it's speaking, the
  // caller's mic input while listening for them.
  const orbVolume = callState === "speaking" ? audio.outputVolume : audio.inputVolume;

  return (
    <div className="relative flex h-full min-h-[360px] flex-col gap-5 overflow-hidden rounded-v-md border border-v-line bg-v-fg p-6 text-white">
      <div className="flex items-center justify-between gap-3">
        <span className="flex items-center gap-1.5 text-[11px] font-medium text-white/60">
          <span
            className={`size-1.5 rounded-full transition-colors ${
              audio.isConnected ? "bg-emerald-400" : "bg-white/30"
            }`}
          />
          {audio.status}
        </span>
        {audio.isConnected ? (
          <span className="font-mono text-[11px] tabular-nums text-white/60">{formatDuration(seconds)}</span>
        ) : null}
      </div>

      {!audio.isConnected ? (
        // Idle — a centered "Start test call" button over a blurred backdrop,
        // and where the call resets back to once "End call" is pressed.
        <div className="relative flex flex-1 items-center justify-center">
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center opacity-[0.06] blur-2xl">
            <Orb theme="bars" state="idle" volume={0} size={192} interactive={false} aria-hidden />
          </div>
          <div className="relative flex flex-col items-center gap-4 rounded-v-md border border-white/10 bg-white/5 px-12 py-10 backdrop-blur-md">
            <Orb theme="bars" state="idle" volume={0} size={64} interactive={false} aria-label="Ready to call" />
            <span className="font-mono text-[11px] uppercase tracking-[.14em] text-white/50">Ready to call</span>
            <Button size="md" onClick={() => audio.connect()}>
              Start test call
            </Button>
          </div>
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-1 gap-5 sm:grid-cols-[176px_minmax(0,1fr)]">
          {/* Left: avatar, state, and the only two controls that matter mid-call. */}
          <div className="flex flex-col items-center justify-center gap-4">
            <div className="relative flex h-28 w-28 items-center justify-center">
              <Orb
                theme="bars"
                state={callState === "speaking" ? "speaking" : "listening"}
                volume={orbVolume}
                size={112}
                interactive={false}
                aria-label={callState === "speaking" ? "Agent speaking" : "Listening"}
              />
            </div>
            <span className="font-mono text-[11px] uppercase tracking-[.14em] text-white/50">
              {callState === "speaking" ? "Agent speaking" : "Listening"}
            </span>

            <div className="flex items-center gap-2">
              <button
                type="button"
                aria-label={audio.isMuted ? "Unmute microphone" : "Mute microphone"}
                aria-pressed={audio.isMuted}
                onClick={() => audio.toggleMute()}
                className={`flex size-11 cursor-pointer items-center justify-center rounded-full transition-colors ${
                  audio.isMuted ? "bg-white/15 text-white/70 hover:bg-white/25" : "bg-white text-v-fg hover:bg-white/90"
                }`}
              >
                {audio.isMuted ? (
                  <MicOff className="size-5" strokeWidth={1.75} />
                ) : (
                  <Mic className="size-5" strokeWidth={1.75} />
                )}
              </button>

              <button
                type="button"
                aria-label="End call"
                onClick={() => audio.disconnect()}
                className="flex size-11 cursor-pointer items-center justify-center rounded-full bg-v-danger text-white transition-colors hover:bg-red-600"
              >
                <PhoneOff className="size-5" strokeWidth={1.75} />
              </button>
            </div>
          </div>

          {/* Right: the transcript, flowing "Label: text" per line. */}
          <div
            ref={transcriptRef}
            className="flex max-h-[min(320px,42vh)] min-h-40 min-w-0 flex-col gap-2 overflow-y-scroll overscroll-contain rounded-v-sm bg-white/5 p-4 [scrollbar-color:rgba(255,255,255,0.35)_transparent] [scrollbar-width:thin] [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-white/35 [&::-webkit-scrollbar-track]:bg-transparent"
          >
            {!hasTranscript ? (
              <span className="text-xs text-white/40">Speak after the greeting — the transcript appears here.</span>
            ) : null}

            {audio.transcriptHistory.map((m) => (
              <p key={m.id} className="text-[14px] leading-relaxed">
                <span className="font-semibold text-white/60">{m.type === "assistant" ? "Agent:" : "User:"}</span>{" "}
                {m.content}
              </p>
            ))}
            {audio.liveUserText ? (
              <p className="text-[14px] leading-relaxed opacity-70">
                <span className="font-semibold text-white/60">User:</span> {audio.liveUserText}
              </p>
            ) : null}
            {audio.liveAssistantText ? (
              <p className="text-[14px] leading-relaxed opacity-70">
                <span className="font-semibold text-white/60">Agent:</span> {audio.liveAssistantText}
              </p>
            ) : null}
          </div>
        </div>
      )}

      <span className="sr-only" aria-live="polite">
        {agentName} test call is {callState === "idle" ? "not started" : callState}
      </span>
    </div>
  );
}
