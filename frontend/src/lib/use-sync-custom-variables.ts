"use client";

import { useEffect } from "react";
import { extractVariableNames } from "@/components/wizard/PromptEditor";
import type { AgentForm } from "@/lib/wizard-data";

/** Keeps `form.customVariables` in lockstep with every `{{var}}` referenced
 * anywhere it can appear (prompt, greeting): adds newly-typed ones with an
 * empty default, drops ones no longer referenced. Shared by the create and
 * edit wizards since both own `form` independently. */
export function useSyncCustomVariables(
  form: Pick<AgentForm, "prompt" | "welcome" | "customVariables">,
  onChange: <K extends keyof AgentForm>(key: K, value: AgentForm[K]) => void,
) {
  useEffect(() => {
    const names = Array.from(
      new Set([...extractVariableNames(form.prompt), ...extractVariableNames(form.welcome)]),
    );
    const current = form.customVariables;
    const currentKeys = Object.keys(current);
    const sameSet = currentKeys.length === names.length && names.every((n) => n in current);
    if (sameSet) return;
    const next: Record<string, string> = {};
    for (const name of names) next[name] = current[name] ?? "";
    onChange("customVariables", next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.prompt, form.welcome]);
}
