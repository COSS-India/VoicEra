"use client";

import { Input } from "@/components/ui/Field";
import { InfoTip } from "@/components/ui/Tooltip";
import type { AgentForm } from "@/lib/wizard-data";

/**
 * Default-value editor for every `{{var}}` currently referenced anywhere in
 * the agent (prompt, greeting, ...) — shared by every step that can define a
 * variable, so there's one place to set its value rather than a copy per step.
 */
export function VariablesPanel({
  form,
  onChange,
}: {
  form: Pick<AgentForm, "customVariables">;
  onChange: <K extends keyof AgentForm>(key: K, value: AgentForm[K]) => void;
}) {
  const variableNames = Object.keys(form.customVariables);
  if (variableNames.length === 0) return null;

  return (
    <div className="flex flex-col gap-3 rounded-v-md border border-v-line bg-white p-5">
      <span className="flex items-center gap-2 text-[14.5px] font-semibold">
        Variables
        <InfoTip text="Default values used when a call doesn't supply its own — e.g. from a campaign's CSV columns." />
      </span>
      <div className="flex flex-col gap-2.5">
        {variableNames.map((name) => (
          <label key={name} className="flex items-center gap-3">
            <span className="w-max shrink-0 rounded-v-sm border border-purple-500/20 bg-purple-500/10 px-1.5 py-0.5 font-mono text-[12.5px] font-medium text-purple-700">
              {`{{${name}}}`}
            </span>
            <Input
              value={form.customVariables[name] ?? ""}
              onChange={(e) => onChange("customVariables", { ...form.customVariables, [name]: e.target.value })}
              placeholder="Default value (optional)…"
              className="flex-1"
            />
          </label>
        ))}
      </div>
    </div>
  );
}
