import { Monitor, PhoneIncoming, PhoneOutgoing } from "lucide-react";
import type { CallType } from "@/lib/api-types";

/** Single source of truth for call-type icon/label/color, so History, the call
 * detail sheet, and anywhere else showing a call type never drift apart. */
export const CALL_TYPE_META: Record<CallType, { label: string; icon: typeof PhoneIncoming; className: string }> = {
  inbound: {
    label: "Inbound",
    icon: PhoneIncoming,
    className: "border-v-warning bg-v-warning-pale text-v-warning-deep",
  },
  outbound: {
    label: "Outbound",
    icon: PhoneOutgoing,
    className: "border-v-accent bg-v-pale text-v-accent-deep",
  },
  web: {
    label: "Web",
    icon: Monitor,
    className: "border-v-success bg-v-success-pale text-v-success-deep",
  },
};

export function CallTypeBadge({ type }: { type: CallType }) {
  const meta = CALL_TYPE_META[type];
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 font-mono text-[9.5px] tracking-[.12em] uppercase ${meta.className}`}
    >
      <meta.icon className="size-3" strokeWidth={2} />
      {meta.label}
    </span>
  );
}
