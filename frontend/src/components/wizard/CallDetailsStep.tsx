"use client";

import { Plus, X } from "lucide-react";
import { Input } from "@/components/ui/Field";
import { Switch } from "@/components/ui/Switch";
import { InfoTip } from "@/components/ui/Tooltip";
import { TIPS, type AgentForm } from "@/lib/wizard-data";

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
            min={1}
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
          title="Hold phrases"
          subtitle="Played back if the agent takes a moment to respond, so the line doesn't feel dead."
          tip={TIPS.holds}
        />
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
    </div>
  );
}
