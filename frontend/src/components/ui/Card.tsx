import { HTMLAttributes } from "react";

export function Card({
  className = "",
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      data-card
      className={`rounded-v-xl border border-v-line bg-v-panel shadow-[var(--v-shadow-card)] ${className}`}
      {...props}
    />
  );
}

export function StatCard({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <Card className="flex flex-col gap-2 p-4.5">
      <span className="font-mono text-[9.5px] tracking-[.14em] uppercase text-v-muted">
        {label}
      </span>
      <span className="text-[27px] font-semibold tracking-tight tabular-nums">
        {value}
      </span>
      {note ? <span className="text-xs text-v-muted font-light">{note}</span> : null}
    </Card>
  );
}
