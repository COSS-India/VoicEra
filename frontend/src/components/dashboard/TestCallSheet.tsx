"use client";

import { useMemo, useState } from "react";
import { Info, Phone } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { Spinner } from "@/components/ui/Spinner";
import { Sheet, SheetHeader } from "@/components/ui/Sheet";
import { createOutboundCall } from "@/lib/api/calls";
import type { AgentApiResponse } from "@/lib/api-types";

const E164_RE = /^\+[1-9]\d{6,14}$/;

function agentCustomVariableEntries(agent: AgentApiResponse): [string, string][] {
  const vars = agent.config?.custom_variables ?? {};
  return Object.entries(vars).map(([key, value]) => [
    key,
    value == null ? "" : typeof value === "string" ? value : String(value),
  ]);
}

interface TestCallSheetProps {
  agent: AgentApiResponse;
  onClose: () => void;
  onNotify: (title: string, note: string) => void;
}

export function TestCallSheet({ agent, onClose, onNotify }: TestCallSheetProps) {
  const variableKeys = useMemo(() => agentCustomVariableEntries(agent).map(([key]) => key), [agent]);
  const [toNumber, setToNumber] = useState("+91");
  const [submitting, setSubmitting] = useState(false);
  const [variableValues, setVariableValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(agentCustomVariableEntries(agent)),
  );

  const callerId = agent.linked_phone_number;
  const trimmed = toNumber.trim();
  const validNumber = E164_RE.test(trimmed);

  async function handleCall() {
    if (!validNumber || !callerId) return;
    setSubmitting(true);
    try {
      const custom_variables = Object.fromEntries(
        variableKeys.map((key) => [key, variableValues[key] ?? ""]),
      );
      const call = await createOutboundCall({
        agent_id: agent.agent_id,
        to_number: trimmed,
        ...(variableKeys.length > 0 ? { custom_variables } : {}),
      });
      onNotify("Test call started", `Calling ${trimmed} — status: ${call.status}.`);
      onClose();
    } catch (err) {
      onNotify("Couldn't start test call", err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Sheet open onClose={onClose}>
      <SheetHeader
        title={agent.name}
        subtitle="Initiate a test call to verify your agent configuration"
        icon={<Phone className="size-4" strokeWidth={1.75} />}
        onClose={onClose}
      />

      <div className="flex flex-1 flex-col gap-6 overflow-y-auto p-5">
        <div className="flex flex-col gap-2">
          <label htmlFor="test-call-to" className="text-[14px] font-semibold">
            Your Test Phone Number <span className="text-v-danger">*</span>
          </label>
          <div className="flex items-center gap-2.5 rounded-v-sm border border-v-line-strong bg-white px-3.5 py-3">
            <Phone className="size-4 shrink-0 text-v-muted" strokeWidth={1.75} />
            <input
              id="test-call-to"
              type="tel"
              value={toNumber}
              onChange={(e) => setToNumber(e.target.value)}
              placeholder="+91XXXXXXXXXX"
              className="w-full bg-transparent text-[15px] text-v-fg outline-none"
            />
          </div>
          <p className="flex items-start gap-1.5 text-[12.5px] leading-relaxed text-v-muted">
            <Info className="mt-0.5 size-3.5 shrink-0" strokeWidth={1.75} />
            Enter your phone number in E.164 format. Include country code (e.g., +1 for US, +91 for
            India)
          </p>
        </div>

        <div className="flex flex-col gap-2">
          <span className="text-[14px] font-semibold">Caller ID</span>
          {callerId ? (
            <>
              <div className="flex items-center justify-between gap-3 rounded-v-sm bg-v-soft px-3.5 py-3">
                <span className="font-mono text-[13px] text-v-muted-2">{callerId}</span>
                <span className="shrink-0 text-[11px] text-v-muted">Not editable</span>
              </div>
              <p className="flex items-start gap-1.5 text-[12.5px] leading-relaxed text-v-muted">
                <Info className="mt-0.5 size-3.5 shrink-0" strokeWidth={1.75} />
                This is the phone number that will appear on your caller ID when you receive the test
                call. <span className="text-v-accent">(This cannot be changed)</span>
              </p>
            </>
          ) : (
            <p className="rounded-v-sm border border-v-danger-line bg-v-danger-pale px-3.5 py-3 text-[13px] text-v-danger">
              This agent has no phone number attached yet — attach one from the Numbers page before
              placing a test call.
            </p>
          )}
        </div>

        {variableKeys.length > 0 ? (
          <div className="flex flex-col gap-2.5">
            <div className="flex flex-col gap-1">
              <span className="text-[14px] font-semibold">Custom variables</span>
              <p className="text-[12.5px] leading-relaxed text-v-muted">
                From this agent&apos;s config — override values for this test call only.
              </p>
            </div>
            <div className="flex flex-col gap-2.5">
              {variableKeys.map((key) => (
                <label key={key} className="flex items-center gap-3">
                  <span className="w-max shrink-0 rounded-v-sm border border-purple-500/20 bg-purple-500/10 px-1.5 py-0.5 font-mono text-[12.5px] font-medium text-purple-700">
                    {`{{${key}}}`}
                  </span>
                  <Input
                    value={variableValues[key] ?? ""}
                    onChange={(e) =>
                      setVariableValues((prev) => ({ ...prev, [key]: e.target.value }))
                    }
                    placeholder="Value for this call…"
                    aria-label={`Value for ${key}`}
                    className="flex-1"
                  />
                </label>
              ))}
            </div>
          </div>
        ) : null}
      </div>

      <div className="flex flex-col gap-2.5 border-t border-v-line p-5">
        <Button variant="ghost" onClick={onClose} className="w-full justify-center">
          Cancel
        </Button>
        <Button
          onClick={handleCall}
          disabled={!validNumber || !callerId || submitting}
          className="w-full justify-center"
        >
          {submitting ? <Spinner /> : <Phone className="size-4" strokeWidth={1.75} />}
          Make Test Call
        </Button>
      </div>
    </Sheet>
  );
}
