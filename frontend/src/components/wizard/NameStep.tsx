"use client";

import { Input } from "@/components/ui/Field";
import { Switch } from "@/components/ui/Switch";
import { InfoTip } from "@/components/ui/Tooltip";
import { PromptEditor } from "@/components/wizard/PromptEditor";
import { AGENT_NAME_MAX_LENGTH, TIPS, type AgentForm } from "@/lib/wizard-data";

interface NameStepProps {
  form: AgentForm;
  onChange: <K extends keyof AgentForm>(key: K, value: AgentForm[K]) => void;
}

export function NameStep({ form, onChange }: NameStepProps) {
  const hasGreeting = Boolean(form.welcome.trim());

  return (
    <div className="flex flex-col gap-6 animate-v-rise">
      <div className="flex flex-col gap-5">
        <label className="flex flex-col gap-1.5 text-[13px] font-semibold">
          <span className="flex items-center justify-between gap-1.5">
            <span className="flex items-center gap-1.5">
              Agent name
              <InfoTip text={TIPS.name} />
            </span>
            <span className="text-[11px] font-normal text-v-muted">
              {form.name.length}/{AGENT_NAME_MAX_LENGTH}
            </span>
          </span>
          <Input
            data-tour="agent-name-input"
            value={form.name}
            maxLength={AGENT_NAME_MAX_LENGTH}
            onChange={(e) => onChange("name", e.target.value.slice(0, AGENT_NAME_MAX_LENGTH))}
            placeholder="e.g. Mandi Rate Advisory"
          />
        </label>

        <label className="flex flex-col gap-1.5 text-[13px] font-semibold">
          <span className="flex items-center gap-1.5">
            Greeting message
            <InfoTip text={TIPS.welcome} />
          </span>
          <div data-tour="greeting-input">
            <PromptEditor
              value={form.welcome}
              onChange={(v) => onChange("welcome", v)}
              variables={Object.keys(form.customVariables)}
              placeholder="Namaste, VoicEra se bol raha hoon"
              rows={1}
              singleLine
            />
          </div>
        </label>
      </div>

      <div className="flex items-center gap-3 rounded-v-md border border-v-line bg-white p-4">
        <Switch
          checked={form.ignoreGreetingSpeech}
          label="Ignore caller speech during the greeting"
          onChange={(checked) => onChange("ignoreGreetingSpeech", checked)}
          disabled={!hasGreeting}
        />
        <span
          className={`flex items-center gap-1.5 text-[13px] font-medium ${hasGreeting ? "text-v-fg" : "text-v-muted"}`}
        >
          Ignore caller speech during the greeting
          <InfoTip
            text={
              hasGreeting
                ? "Avoids the agent getting interrupted mid-hello."
                : "Add a greeting message above first — there's nothing to ignore speech during otherwise."
            }
          />
        </span>
      </div>
    </div>
  );
}
