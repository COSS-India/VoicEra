export function ProgressBar({ pct, thick = false }: { pct: number; thick?: boolean }) {
  return (
    <span
      className={`block w-full overflow-hidden rounded-full bg-v-line ${
        thick ? "h-1.5" : "h-1"
      }`}
    >
      <span
        className="block h-full rounded-full bg-v-accent transition-[width]"
        style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
      />
    </span>
  );
}
