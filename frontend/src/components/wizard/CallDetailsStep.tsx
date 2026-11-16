"use client";

import { useRef, useState } from "react";
import { Plus, Upload, X } from "lucide-react";
import { Input } from "@/components/ui/Field";
import { Spinner } from "@/components/ui/Spinner";
import { Switch } from "@/components/ui/Switch";
import { InfoTip } from "@/components/ui/Tooltip";
import { deleteHoldAudio, uploadHoldAudio } from "@/lib/api/hold-audio";
import { TIPS, type AgentForm, type HoldAudioClipForm } from "@/lib/wizard-data";

const HOLD_AUDIO_MAX_BYTES = 2 * 1024 * 1024;
const HOLD_AUDIO_MAX_CLIPS = 10;

interface CallDetailsStepProps {
  form: AgentForm;
  onChange: <K extends keyof AgentForm>(key: K, value: AgentForm[K]) => void;
}

function SectionHeader({ title, subtitle, tip }: { title: string; subtitle: string; tip: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[14.5px] font-semibold text-v-fg">{title}</span>
      <span className="flex items-center gap-1.5 text-[12px] font-light text-v-muted">
        {subtitle}
        <InfoTip text={tip} />
      </span>
    </div>
  );
}

function stepDecimals(step: number): number {
  const text = String(step);
  const dot = text.indexOf(".");
  return dot === -1 ? 0 : text.length - dot - 1;
}

function roundToStep(value: number, step: number): number {
  const decimals = stepDecimals(step);
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor;
}

function formatNumberFieldValue(value: number, step: number): string {
  const decimals = stepDecimals(step);
  return decimals === 0 ? String(value) : value.toFixed(decimals);
}

function NumberField({
  label,
  tipKey,
  value,
  unit,
  min,
  max,
  step = 1,
  onChange,
}: {
  label: string;
  tipKey: string;
  value: number;
  unit?: string;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
}) {
  return (
    <label className="flex flex-col gap-1.5 text-[13px] font-semibold">
      <span className="flex items-center justify-between gap-1.5">
        <span className="flex items-center gap-1.5">
          {label}
          <InfoTip text={TIPS[tipKey] ?? ""} />
        </span>
        <span className="font-mono text-[11px] font-normal text-v-muted">
          {formatNumberFieldValue(value, step)}
          {unit}
        </span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(roundToStep(Number(e.target.value), step))}
        className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-v-line accent-v-accent"
      />
    </label>
  );
}

export function CallDetailsStep({ form, onChange }: CallDetailsStepProps) {
  const [uploadingHoldAudio, setUploadingHoldAudio] = useState(false);
  const [holdAudioError, setHoldAudioError] = useState("");
  const holdAudioInputRef = useRef<HTMLInputElement>(null);

  function updateHold(index: number, value: string) {
    const next = [...form.holdPhrases];
    next[index] = value;
    onChange("holdPhrases", next);
  }

  function addHold() {
    onChange("holdPhrases", [...form.holdPhrases, ""]);
  }

  function removeHold(index: number) {
    onChange(
      "holdPhrases",
      form.holdPhrases.filter((_, i) => i !== index),
    );
  }

  async function handleHoldAudioFiles(fileList: FileList | null) {
    if (!fileList?.length) return;
    setHoldAudioError("");

    const remaining = HOLD_AUDIO_MAX_CLIPS - form.holdAudioClips.length;
    if (remaining <= 0) {
      setHoldAudioError(`At most ${HOLD_AUDIO_MAX_CLIPS} hold clips are allowed.`);
      return;
    }

    const files = Array.from(fileList).slice(0, remaining);
    setUploadingHoldAudio(true);
    const added: HoldAudioClipForm[] = [];
    try {
      for (const file of files) {
        const lower = file.name.toLowerCase();
        if (!lower.endsWith(".wav") && !lower.endsWith(".mp3")) {
          setHoldAudioError("Only WAV and MP3 files are supported.");
          continue;
        }
        if (file.size > HOLD_AUDIO_MAX_BYTES) {
          setHoldAudioError(
            `Each file must be at most ${HOLD_AUDIO_MAX_BYTES / (1024 * 1024)} MB.`,
          );
          continue;
        }
        const uploaded = await uploadHoldAudio(file);
        added.push({
          clipId: uploaded.clip_id,
          storageKey: uploaded.storage_key,
          filename: uploaded.filename,
        });
      }
      if (added.length) {
        onChange("holdAudioClips", [...form.holdAudioClips, ...added]);
      }
    } catch (err) {
      setHoldAudioError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setUploadingHoldAudio(false);
      if (holdAudioInputRef.current) holdAudioInputRef.current.value = "";
    }
  }

  async function removeHoldAudio(index: number) {
    const clip = form.holdAudioClips[index];
    if (!clip) return;
    onChange(
      "holdAudioClips",
      form.holdAudioClips.filter((_, i) => i !== index),
    );
    try {
      await deleteHoldAudio(clip.clipId, clip.storageKey);
    } catch {
      // Form already updated; orphaned MinIO object is acceptable.
    }
  }

  return (
    <div data-tour="call-details-step" className="flex flex-col gap-6 animate-v-rise">
      <div className="flex flex-col gap-5 rounded-v-md border border-v-line bg-white p-5">
        <SectionHeader
          title="Timing & limits"
          subtitle="How long the agent waits before interrupting, hanging up, or giving up."
          tip="Controls how the agent reacts to pauses and silence, and puts a hard ceiling on how long any one call can run."
        />
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <NumberField
            label="Interrupt threshold"
            tipKey="interrupt"
            unit=" words"
            value={form.interruptThreshold}
            min={0}
            max={10}
            onChange={(v) => onChange("interruptThreshold", v)}
          />
          <NumberField
            label="Silence hangup"
            tipKey="silence"
            unit="s"
            value={form.silenceTimeout}
            min={0}
            max={120}
            step={5}
            onChange={(v) => onChange("silenceTimeout", v)}
          />
          <NumberField
            label="Total call limit"
            tipKey="timeout"
            unit="s"
            value={form.callLimit}
            min={60}
            max={3600}
            step={30}
            onChange={(v) => onChange("callLimit", v)}
          />
          <NumberField
            label="Hold message timeout"
            tipKey="holdTimeout"
            unit="s"
            value={form.holdMessageTimeoutSeconds}
            min={0}
            max={30}
            step={0.1}
            onChange={(v) => onChange("holdMessageTimeoutSeconds", v)}
          />
        </div>
      </div>

      <div className="flex flex-col gap-3 rounded-v-md border border-v-line bg-white p-5">
        <SectionHeader
          title="Hold messages"
          subtitle="Played if the agent takes a moment to respond, so the line doesn't feel dead."
          tip={TIPS.holds}
        />
        <div className="flex items-center gap-3">
          <Switch
            checked={form.holdMode === "audio"}
            onCheckedChange={(checked) => onChange("holdMode", checked ? "audio" : "text")}
          />
          <span className="flex items-center gap-1.5 text-[13px] font-medium text-v-fg">
            Use uploaded WAV clips instead of text phrases
            <InfoTip text={TIPS.holdMode} />
          </span>
        </div>

        {form.holdMode === "text" ? (
          <>
            <div className="flex flex-col gap-2.5">
              {form.holdPhrases.map((phrase, i) => (
                <div key={i} className="flex items-center gap-2">
                  <Input
                    value={phrase}
                    onChange={(e) => updateHold(i, e.target.value)}
                    placeholder="Ek minute dekh raha hoon"
                    className="flex-1"
                  />
                  <button
                    type="button"
                    onClick={() => removeHold(i)}
                    aria-label="Remove phrase"
                    className="flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-v-md border border-v-line text-v-muted transition-colors hover:bg-v-soft hover:text-v-fg"
                  >
                    <X className="size-4" strokeWidth={1.8} />
                  </button>
                </div>
              ))}
            </div>
            <button
              type="button"
              onClick={addHold}
              className="flex w-max cursor-pointer items-center gap-1.5 text-xs font-medium text-v-accent hover:text-v-accent-deep"
            >
              <Plus className="size-3.5" strokeWidth={2} />
              Add phrase
            </button>
          </>
        ) : (
          <>
            <p className="text-[12px] font-light text-v-muted">
              WAV (16-bit PCM) or MP3, up to {HOLD_AUDIO_MAX_CLIPS} clips /{" "}
              {HOLD_AUDIO_MAX_BYTES / (1024 * 1024)} MB each.
              <InfoTip text={TIPS.holdAudio} />
            </p>
            {form.holdAudioClips.length > 0 && (
              <div className="flex flex-col gap-2.5">
                {form.holdAudioClips.map((clip, i) => (
                  <div
                    key={clip.clipId}
                    className="flex items-center gap-2 rounded-v-md border border-v-line bg-v-soft px-3 py-2"
                  >
                    <span className="min-w-0 flex-1 truncate text-[13px] text-v-fg">
                      {clip.filename}
                    </span>
                    <button
                      type="button"
                      onClick={() => void removeHoldAudio(i)}
                      aria-label="Remove clip"
                      className="flex size-9 shrink-0 cursor-pointer items-center justify-center rounded-v-md border border-v-line text-v-muted transition-colors hover:bg-white hover:text-v-fg"
                    >
                      <X className="size-4" strokeWidth={1.8} />
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                void handleHoldAudioFiles(e.dataTransfer.files);
              }}
              onClick={() => {
                if (!uploadingHoldAudio && form.holdAudioClips.length < HOLD_AUDIO_MAX_CLIPS) {
                  holdAudioInputRef.current?.click();
                }
              }}
              className={`flex cursor-pointer flex-col items-center gap-2 rounded-v-md border border-dashed p-6 text-center transition-colors ${
                uploadingHoldAudio
                  ? "border-v-line bg-v-soft opacity-70"
                  : "border-v-line bg-v-soft hover:border-v-accent"
              }`}
            >
              {uploadingHoldAudio ? (
                <Spinner light={false} />
              ) : (
                <Upload className="size-5 text-v-muted" strokeWidth={1.75} />
              )}
              <span className="text-sm font-semibold">
                {uploadingHoldAudio ? "Uploading…" : "Drop WAV or MP3 files here"}
              </span>
              <span className="text-xs text-v-muted">or click to choose</span>
              <input
                ref={holdAudioInputRef}
                type="file"
                accept=".wav,.mp3,audio/wav,audio/x-wav,audio/mpeg"
                multiple
                className="hidden"
                onChange={(e) => void handleHoldAudioFiles(e.target.files)}
              />
            </div>
            {holdAudioError ? (
              <p className="text-[12px] font-medium text-red-600">{holdAudioError}</p>
            ) : null}
          </>
        )}
      </div>

      <div className="flex flex-col gap-4 rounded-v-md border border-v-line bg-white p-5">
        <SectionHeader
          title="Check caller still there"
          subtitle="Detects a silent caller and gently checks the line is still connected."
          tip={TIPS.online}
        />
        <div className="flex items-center gap-3">
          <Switch
            checked={form.checkStillThere}
            label="Check caller still there"
            onChange={(checked) => onChange("checkStillThere", checked)}
          />
          <span className="text-[13px] font-medium text-v-fg">Check caller still there</span>
        </div>

        {form.checkStillThere ? (
          <div className="grid grid-cols-1 gap-4 border-t border-v-line pt-4 sm:grid-cols-2">
            <label className="flex flex-col gap-1.5 text-[13px] font-semibold sm:col-span-2">
              <span className="flex items-center gap-1.5">
                Check-in message
                <InfoTip text={TIPS.onlineMessage} />
              </span>
              <Input
                value={form.onlineDetectionMessage}
                onChange={(e) => onChange("onlineDetectionMessage", e.target.value)}
                placeholder="Are you still there?"
              />
            </label>

            <NumberField
              label="Silence before checking"
              tipKey="onlineSeconds"
              unit="s"
              value={form.onlineDetectionSeconds}
              min={0}
              max={180}
              step={0.1}
              onChange={(v) => onChange("onlineDetectionSeconds", v)}
            />
            <NumberField
              label="Repeat count"
              tipKey="onlineRepeats"
              unit=" time(s)"
              value={form.onlineDetectionRepeats}
              min={1}
              max={5}
              onChange={(v) => onChange("onlineDetectionRepeats", v)}
            />

            <label className="flex flex-col gap-1.5 text-[13px] font-semibold sm:col-span-2">
              <span className="flex items-center gap-1.5">
                Closing message
                <InfoTip text={TIPS.onlineClosing} />
              </span>
              <Input
                value={form.onlineDetectionClosingMessage}
                onChange={(e) => onChange("onlineDetectionClosingMessage", e.target.value)}
                placeholder="I'll end the call now. Goodbye."
              />
            </label>
          </div>
        ) : null}
      </div>

      <div className="flex flex-col gap-4 rounded-v-md border border-v-line bg-white p-5">
        <SectionHeader
          title="Automatic call ending"
          subtitle="Lets the agent end the call itself once the conversation is done."
          tip={TIPS.autoEnding}
        />
        <div className="flex items-center gap-3">
          <Switch
            checked={form.autoCallEndingEnabled}
            label="Let the agent end the call automatically"
            onChange={(checked) => onChange("autoCallEndingEnabled", checked)}
          />
          <span className="text-[13px] font-medium text-v-fg">Let the agent end the call automatically</span>
        </div>

        {form.autoCallEndingEnabled ? (
          <div className="flex items-center gap-3 border-t border-v-line pt-4">
            <Switch
              checked={form.autoCallEndingGraceful}
              label="Graceful ending"
              onChange={(checked) => onChange("autoCallEndingGraceful", checked)}
            />
            <span className="flex items-center gap-1.5 text-[13px] font-medium text-v-fg">
              Graceful ending
              <InfoTip text={TIPS.autoEndingGraceful} />
            </span>
          </div>
        ) : null}
      </div>

      <div className="flex flex-col gap-5 rounded-v-md border border-v-line bg-white p-5">
        <SectionHeader
          title="VAD while speaking"
          subtitle="Used while the agent is talking. Higher confidence / volume makes barge-in harder, so noise and short sounds are less likely to interrupt the agent."
          tip="Applied when the agent is speaking (same bot-speaking signal as interrupt threshold). Tune this to control how easy it is to barge in."
        />
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <NumberField
            label="Confidence"
            tipKey="vadConfidence"
            value={form.vadConfidence}
            min={0}
            max={1}
            step={0.1}
            onChange={(v) => onChange("vadConfidence", v)}
          />
          <NumberField
            label="Speech start"
            tipKey="vadStartSecs"
            unit="s"
            value={form.vadStartSecs}
            min={0}
            max={2}
            step={0.1}
            onChange={(v) => onChange("vadStartSecs", v)}
          />
          <NumberField
            label="Speech stop"
            tipKey="vadStopSecs"
            unit="s"
            value={form.vadStopSecs}
            min={0}
            max={2}
            step={0.1}
            onChange={(v) => onChange("vadStopSecs", v)}
          />
          <NumberField
            label="Min volume"
            tipKey="vadMinVolume"
            value={form.vadMinVolume}
            min={0}
            max={1}
            step={0.1}
            onChange={(v) => onChange("vadMinVolume", v)}
          />
        </div>
      </div>

      <div className="flex flex-col gap-5 rounded-v-md border border-v-line bg-white p-5">
        <SectionHeader
          title="VAD while idle"
          subtitle="Used when the agent is silent and waiting for the caller. Lower confidence / volume makes the agent pick up quiet or short replies faster."
          tip="Applied when the agent is not speaking. Tune this for how quickly the agent hears the caller after it finishes talking."
        />
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <NumberField
            label="Confidence"
            tipKey="vadIdleConfidence"
            value={form.vadIdleConfidence}
            min={0}
            max={1}
            step={0.1}
            onChange={(v) => onChange("vadIdleConfidence", v)}
          />
          <NumberField
            label="Speech start"
            tipKey="vadIdleStartSecs"
            unit="s"
            value={form.vadIdleStartSecs}
            min={0}
            max={2}
            step={0.1}
            onChange={(v) => onChange("vadIdleStartSecs", v)}
          />
          <NumberField
            label="Speech stop"
            tipKey="vadIdleStopSecs"
            unit="s"
            value={form.vadIdleStopSecs}
            min={0}
            max={2}
            step={0.1}
            onChange={(v) => onChange("vadIdleStopSecs", v)}
          />
          <NumberField
            label="Min volume"
            tipKey="vadIdleMinVolume"
            value={form.vadIdleMinVolume}
            min={0}
            max={1}
            step={0.1}
            onChange={(v) => onChange("vadIdleMinVolume", v)}
          />
        </div>
      </div>
    </div>
  );
}
