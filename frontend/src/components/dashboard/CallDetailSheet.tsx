"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { Activity, ArrowLeft, Download, Pause, Play } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { CallTypeBadge } from "@/components/ui/CallTypeBadge";
import { Spinner } from "@/components/ui/Spinner";
import { Sheet } from "@/components/ui/Sheet";
import { Tooltip } from "@/components/ui/Tooltip";
import { fetchCallRecordingBlob, fetchCallTranscriptText, getCallMetrics } from "@/lib/api/calls";
import { formatClockLabel, parseTranscript, type TranscriptLine } from "@/lib/transcript";
import { displayFromNumber, displayToNumber, formatDuration } from "@/lib/format";
import type { CallLogItem } from "@/lib/api-types";

function formatDateTime(iso?: string | null): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "–";
  return d.toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function fmtClock(t: number): string {
  if (!Number.isFinite(t)) return "0:00";
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60)
    .toString()
    .padStart(2, "0");
  return `${m}:${s}`;
}

function statusTone(call: CallLogItem) {
  if (call.status === "failed" || call.call_response === "failed") return "danger" as const;
  if (call.status === "completed") return "live" as const;
  if (call.status === "in_progress" || call.status === "ringing") return "accent" as const;
  return "neutral" as const;
}

function TelemetryButtonIcon() {
  return (
    <span className="flex items-center">
      {/* Lucide ArrowUpRight icon */}
      <svg
        xmlns="http://www.w3.org/2000/svg"
        className="inline-block size-5 align-middle"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        aria-hidden="true"
      >
        <line x1="7" y1="17" x2="17" y2="7" />
        <polyline points="7 7 17 7 17 17" />
      </svg>
    </span>
  );
}

const WAVEFORM_BARS = 72;

/** Downmixes to mono peak buckets for the waveform bars — cheap enough for a
 * call-length clip and only run once per opened call. */
async function computePeaks(blob: Blob, buckets: number): Promise<number[]> {
  const AudioCtxCtor = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  const ctx = new AudioCtxCtor();
  try {
    const arrayBuffer = await blob.arrayBuffer();
    const audioBuffer = await ctx.decodeAudioData(arrayBuffer);
    const channel = audioBuffer.getChannelData(0);
    const perBucket = Math.max(1, Math.floor(channel.length / buckets));
    const peaks: number[] = [];
    for (let i = 0; i < buckets; i++) {
      const start = i * perBucket;
      let sum = 0;
      for (let j = 0; j < perBucket; j++) sum += Math.abs(channel[start + j] ?? 0);
      peaks.push(sum / perBucket);
    }
    const max = Math.max(...peaks, 0.0001);
    return peaks.map((p) => Math.max(0.08, Math.min(1, p / max)));
  } finally {
    ctx.close();
  }
}

interface AudioState {
  url: string | null;
  peaks: number[] | null;
  error: string;
  playing: boolean;
  current: number;
  duration: number;
}

/** Waveform + transport controls. Fitts's Law: the whole bar is one large click
 * target for seeking, not a thin scrubber. Play state is always visible
 * (Nielsen's visibility of system status) via the moving playhead and the
 * played/unplayed bar contrast. */
function WaveformPlayer({
  state,
  onTogglePlay,
  onSeek,
  callId,
}: {
  state: AudioState;
  onTogglePlay: () => void;
  onSeek: (t: number) => void;
  callId: string;
}) {
  const trackRef = useRef<HTMLDivElement>(null);
  const progress = state.duration > 0 ? state.current / state.duration : 0;

  function handleSeekClick(e: React.MouseEvent<HTMLDivElement>) {
    const el = trackRef.current;
    if (!el || !state.duration) return;
    const rect = el.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    onSeek(ratio * state.duration);
  }

  if (state.error) {
    return <div className="rounded-v-md bg-v-fg px-4 py-3 text-[12.5px] text-white/70">{state.error}</div>;
  }

  return (
    <div className="flex items-center gap-3 rounded-v-md bg-v-fg px-4 py-3.5">
      <button
        type="button"
        onClick={onTogglePlay}
        disabled={!state.url}
        aria-label={state.playing ? "Pause" : "Play"}
        className="flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-full bg-white/15 text-white transition-transform hover:bg-white/25 active:scale-90 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {!state.url ? <Spinner /> : state.playing ? <Pause className="size-4" /> : <Play className="size-4" />}
      </button>

      <div
        ref={trackRef}
        onClick={handleSeekClick}
        role="slider"
        aria-label="Seek"
        aria-valuemin={0}
        aria-valuemax={state.duration}
        aria-valuenow={state.current}
        className={`relative flex h-9 flex-1 items-center gap-[2px] ${state.url ? "cursor-pointer" : "cursor-default"}`}
      >
        {state.peaks ? (
          state.peaks.map((p, i) => {
            const played = i / state.peaks!.length <= progress;
            return (
              <span
                key={i}
                className={`w-full rounded-full transition-colors duration-150 ${played ? "bg-white" : "bg-white/25"}`}
                style={{ height: `${Math.round(p * 100)}%` }}
              />
            );
          })
        ) : (
          <div className="flex h-full w-full items-center gap-0.5">
            {Array.from({ length: WAVEFORM_BARS }).map((_, i) => (
              <span key={i} className="h-2/5 w-full animate-pulse rounded-full bg-white/15" />
            ))}
          </div>
        )}
      </div>

      <span className="shrink-0 font-mono text-[11px] text-white/70">
        {fmtClock(state.current)} / {fmtClock(state.duration)}
      </span>
      {state.url ? (
        <a
          href={state.url}
          download={`${callId}.wav`}
          aria-label="Download recording"
          className="flex size-9 shrink-0 items-center justify-center rounded-full bg-white/15 text-white transition-colors hover:bg-white/25"
        >
          <Download className="size-4" strokeWidth={1.75} />
        </a>
      ) : null}
    </div>
  );
}

function TranscriptBubble({
  line,
  active,
  onSeek,
}: {
  line: TranscriptLine;
  active: boolean;
  onSeek: (t: number) => void;
}) {
  const isUser = line.role === "user";
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (active) ref.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [active]);

  return (
    <div
      ref={ref}
      className={`flex items-start gap-2.5 ${isUser ? "flex-row-reverse" : ""}`}
    >
      <span
        className={`flex size-7 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${
          isUser ? "bg-v-accent text-white" : "bg-v-soft text-v-muted-2"
        }`}
      >
        {isUser ? "U" : "A"}
      </span>
      <div className={`flex max-w-[75%] flex-col gap-1 ${isUser ? "items-end" : "items-start"}`}>
        <span className="font-mono text-[10px] text-v-muted">{formatClockLabel(line.timestamp)}</span>
        <button
          type="button"
          onClick={() => onSeek(line.offsetSeconds)}
          title="Play from here"
          className={`cursor-pointer rounded-v-sm px-3.5 py-2.5 text-left text-[13px] leading-relaxed transition-all ${
            isUser
              ? `bg-v-accent text-white hover:bg-v-accent-deep ${active ? "ring-2 ring-v-accent-deep ring-offset-1" : ""}`
              : `border bg-white text-v-fg hover:border-v-accent ${active ? "border-v-accent ring-2 ring-v-accent/30" : "border-v-line"}`
          }`}
        >
          {line.content}
        </button>
      </div>
    </div>
  );
}

export function CallDetailSheet({
  call,
  onClose,
  showTelemetryLink = true,
}: {
  call: CallLogItem;
  onClose: () => void;
  /** Hide the "View Call Telemetry" link when the sheet is already opened
   * from the Telemetry page itself — linking back to where you already are. */
  showTelemetryLink?: boolean;
}) {
  const [tab, setTab] = useState<"transcript" | "details">("transcript");
  const [transcript, setTranscript] = useState<TranscriptLine[] | null>(null);
  const [transcriptError, setTranscriptError] = useState("");
  const [transcriptRaw, setTranscriptRaw] = useState("");
  const [audio, setAudio] = useState<AudioState>({
    url: null,
    peaks: null,
    error: "",
    playing: false,
    current: 0,
    duration: 0,
  });
  const audioElRef = useRef<HTMLAudioElement>(null);
  const [hasLatencyData, setHasLatencyData] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setHasLatencyData(false);
    getCallMetrics(call.call_id)
      .then(() => {
        if (!cancelled) setHasLatencyData(true);
      })
      .catch(() => {
        /* 404/no metrics yet — leave the telemetry link hidden for this call. */
      });
    return () => {
      cancelled = true;
    };
  }, [call.call_id]);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;
    fetchCallRecordingBlob(call.call_id)
      .then(async (blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setAudio((s) => ({ ...s, url: objectUrl }));
        try {
          const peaks = await computePeaks(blob, WAVEFORM_BARS);
          if (!cancelled) setAudio((s) => ({ ...s, peaks }));
        } catch {
          /* waveform is a bonus — playback still works without it */
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setAudio((s) => ({ ...s, error: err instanceof Error ? err.message : "Recording unavailable." }));
        }
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [call.call_id]);

  useEffect(() => {
    let cancelled = false;
    setTranscript(null);
    setTranscriptError("");
    fetchCallTranscriptText(call.call_id)
      .then((text) => {
        if (cancelled) return;
        setTranscriptRaw(text);
        setTranscript(parseTranscript(text));
      })
      .catch((err) => {
        if (!cancelled) setTranscriptError(err instanceof Error ? err.message : "No transcript available.");
      });
    return () => {
      cancelled = true;
    };
  }, [call.call_id]);

  function togglePlay() {
    const el = audioElRef.current;
    if (!el) return;
    if (audio.playing) el.pause();
    else el.play();
  }

  function seekTo(t: number) {
    const el = audioElRef.current;
    if (!el || !audio.duration) return;
    el.currentTime = Math.min(audio.duration, Math.max(0, t));
    if (!audio.playing) el.play();
  }

  const activeIndex = useMemo(() => {
    if (!transcript || !audio.playing) return -1;
    let idx = -1;
    for (let i = 0; i < transcript.length; i++) {
      if (transcript[i]!.offsetSeconds <= audio.current) idx = i;
      else break;
    }
    return idx;
  }, [transcript, audio]);

  const detailRows = useMemo(
    () => [
      { label: "Call ID", value: call.call_id },
      { label: "Provider call SID", value: call.provider_call_sid ?? "–" },
      { label: "Telephony provider", value: call.telephony_provider ?? "–" },
      { label: "Call response", value: call.call_response ?? "–" },
      { label: "From", value: displayFromNumber(call) },
      { label: "To", value: displayToNumber(call) },
      { label: "Started", value: formatDateTime(call.start_time_utc ?? call.created_at) },
      { label: "Ended", value: formatDateTime(call.end_time_utc) },
      { label: "Duration", value: formatDuration(call.duration) },
      ...(call.error_message ? [{ label: "Error", value: call.error_message }] : []),
      ...(Object.keys(call.custom_variables ?? {}).length
        ? [{ label: "Custom variables", value: JSON.stringify(call.custom_variables) }]
        : []),
    ],
    [call],
  );

  function downloadTranscript() {
    const blob = new Blob([transcriptRaw], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${call.call_id}-transcript.txt`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <Sheet open onClose={onClose} widthClassName="max-w-xl">
      <div className="flex items-center justify-between gap-3 border-b border-v-line px-5 py-4">
        <span className="flex min-w-0 items-center gap-3">
          <button
            type="button"
            aria-label="Close"
            onClick={onClose}
            className="flex size-8 shrink-0 cursor-pointer items-center justify-center rounded-v-sm text-v-muted transition-colors hover:bg-v-soft hover:text-v-fg"
          >
            <ArrowLeft className="size-4" strokeWidth={1.75} />
          </button>
          <span className="flex min-w-0 flex-col gap-0.5">
            <span className="truncate text-[17px] font-semibold tracking-tight">
              {call.agent_name ?? call.agent_id}
            </span>
            <span className="text-xs font-light text-v-muted">
              {formatDateTime(call.start_time_utc ?? call.created_at)}
            </span>
          </span>
        </span>
        {showTelemetryLink ? (
          hasLatencyData ? (
            <Link
              href={`/telemetry?call=${encodeURIComponent(call.call_id)}`}
              className="flex shrink-0 items-center gap-2 rounded-v-md border border-v-line px-3 py-[7px] text-xs font-medium text-white bg-[#122347] transition-colors duration-[120ms] hover:bg-[#182c5b] hover:text-white"
            >
              <TelemetryButtonIcon />
              <span className="ml-2">View Call Telemetry</span>
            </Link>
          ) : (
            <Tooltip text="No latency data recorded for this call yet.">
              <span
                aria-disabled="true"
                className="flex shrink-0 cursor-not-allowed items-center gap-2 rounded-v-md border border-v-line px-3 py-[7px] text-xs font-medium text-v-faint opacity-60"
              >
                <TelemetryButtonIcon />
                <span className="ml-2">View Call Telemetry</span>
              </span>
            </Tooltip>
          )
        ) : null}
      </div>

      <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-5">
        <WaveformPlayer state={audio} onTogglePlay={togglePlay} onSeek={seekTo} callId={call.call_id} />
        {audio.url ? (
          <audio
            ref={audioElRef}
            src={audio.url}
            onPlay={() => setAudio((s) => ({ ...s, playing: true }))}
            onPause={() => setAudio((s) => ({ ...s, playing: false }))}
            onTimeUpdate={(e) => {
              const current = e.currentTarget.currentTime;
              setAudio((s) => ({ ...s, current }));
            }}
            onLoadedMetadata={(e) => {
              const duration = e.currentTarget.duration || 0;
              setAudio((s) => ({ ...s, duration }));
            }}
            onEnded={() => setAudio((s) => ({ ...s, playing: false }))}
            className="hidden"
          />
        ) : null}

        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-v-muted">{formatDateTime(call.start_time_utc ?? call.created_at)}</span>
          <CallTypeBadge type={call.call_type} />
          <Badge tone={statusTone(call)}>{call.status}</Badge>
        </div>

        <div className="flex items-center justify-between border-b border-v-line">
          <div className="flex gap-4">
            {(["transcript", "details"] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={`cursor-pointer border-b-2 px-1 pb-2.5 text-[13.5px] font-medium capitalize transition-colors ${
                  tab === t ? "border-v-fg text-v-fg" : "border-transparent text-v-muted hover:text-v-fg"
                }`}
              >
                {t}
              </button>
            ))}
          </div>
          {tab === "transcript" && transcript && transcript.length > 0 ? (
            <button
              type="button"
              onClick={downloadTranscript}
              className="mb-2 flex cursor-pointer items-center gap-1.5 text-xs font-medium text-v-muted hover:text-v-accent"
            >
              <Download className="size-3.5" strokeWidth={1.75} />
              Export
            </button>
          ) : null}
        </div>

        {tab === "transcript" ? (
          transcriptError ? (
            <p className="py-8 text-center text-sm text-v-muted">{transcriptError}</p>
          ) : transcript === null ? (
            <div className="flex items-center justify-center gap-2 py-8 text-sm text-v-muted">
              <Spinner light={false} /> Loading transcript…
            </div>
          ) : transcript.length === 0 ? (
            <p className="py-8 text-center text-sm text-v-muted">No transcript for this call.</p>
          ) : (
            <div className="flex flex-col gap-4 rounded-v-md bg-v-soft/40 p-4">
              {transcript.map((line, i) => (
                <TranscriptBubble key={i} line={line} active={i === activeIndex} onSeek={seekTo} />
              ))}
            </div>
          )
        ) : (
          <dl className="flex flex-col gap-3">
            {detailRows.map((row) => (
              <div key={row.label} className="flex items-start justify-between gap-4 border-b border-v-line pb-2.5">
                <dt className="shrink-0 font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">
                  {row.label}
                </dt>
                <dd className="min-w-0 break-words text-right text-[13px] font-medium text-v-fg">
                  {row.value}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </div>
    </Sheet>
  );
}
