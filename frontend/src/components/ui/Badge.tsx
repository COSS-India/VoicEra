type Tone = "neutral" | "accent" | "live" | "draft" | "danger" | "warn";

const tones: Record<Tone, string> = {
  neutral: "bg-v-soft text-v-muted-2 border-v-soft",
  accent: "bg-v-pale text-v-accent border-v-pale", // in-progress — blue tint, not a solid fill
  live: "bg-v-ok-tint text-v-ok-ink border-v-ok-tint",
  warn: "bg-v-warn-tint text-v-warn-ink border-v-warn-tint",
  draft: "bg-v-track text-v-faint border-v-track",
  danger: "bg-v-danger-pale text-v-danger border-v-danger-line",
};

export function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: Tone;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-v-sm border px-2 py-[3px] font-mono text-[10px] font-semibold tracking-[.12em] uppercase ${tones[tone]}`}
    >
      {tone === "live" ? <span className="size-[5px] shrink-0 rounded-full bg-v-ok" /> : null}
      {children}
    </span>
  );
}

export function Tag({ children }: { children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center rounded-v-sm bg-v-track px-2.5 py-1 text-[11px] font-medium text-v-muted-2">
      {children}
    </span>
  );
}
