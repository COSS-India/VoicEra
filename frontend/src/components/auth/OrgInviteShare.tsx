"use client";

import { useMemo, useState } from "react";
import { Check, Copy } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { buildMemberInviteLink } from "@/lib/invite-link";

export function InviteLinkCopy({ orgId, orgName }: { orgId: string; orgName?: string }) {
  const [copied, setCopied] = useState(false);
  const link = useMemo(() => buildMemberInviteLink(orgId, orgName), [orgId, orgName]);

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      /* clipboard unavailable — the input is still selectable/copyable manually */
    }
  }

  return (
    <div className="flex items-center gap-2">
      <input
        readOnly
        value={link}
        onFocus={(e) => e.currentTarget.select()}
        className="min-w-0 flex-1 rounded-v-sm border border-v-line-strong bg-v-soft/50 px-3.5 py-2.5 font-mono text-[12.5px] text-v-fg"
      />
      <Button size="sm" variant="outline" onClick={copyLink} className="shrink-0">
        {copied ? (
          <>
            <Check className="size-3.5" strokeWidth={1.75} /> Copied
          </>
        ) : (
          <>
            <Copy className="size-3.5" strokeWidth={1.75} /> Copy link
          </>
        )}
      </Button>
    </div>
  );
}

export function OrgInviteShare({
  orgId,
  orgName,
  onContinue,
  continueLabel = "Continue",
}: {
  orgId: string;
  orgName: string;
  onContinue: () => void;
  continueLabel?: string;
}) {
  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <span className="font-mono text-[10px] font-semibold uppercase tracking-[.14em] text-v-muted">
          Organisation created
        </span>
        <h2 className="m-0 text-3xl font-semibold tracking-tight">{orgName}</h2>
        <p className="m-0 text-sm font-light leading-relaxed text-v-muted">
          Share this link with teammates. Anyone who opens it can sign up and join{" "}
          {orgName} as a member.
        </p>
      </div>

      <InviteLinkCopy orgId={orgId} orgName={orgName} />

      <button
        type="button"
        onClick={onContinue}
        className="flex w-full cursor-pointer items-center justify-center gap-2.5 rounded-v-sm bg-v-fg px-4.5 py-3.5 text-[15px] font-semibold text-white transition-colors hover:bg-v-accent"
      >
        {continueLabel}
      </button>

      <p className="m-0 text-center text-xs font-light text-v-muted">
        The link stays available under Members.
      </p>
    </div>
  );
}
