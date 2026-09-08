const TICKS = Array.from({ length: 8 });

export function Spinner({ light = true }: { light?: boolean }) {
  return (
    <span className="relative block h-[18px] w-[18px]">
      {TICKS.map((_, i) => (
        <span
          key={i}
          style={{
            transform: `rotate(${i * 45}deg)`,
            transformOrigin: "50% 9px",
            animationDelay: `${i * 0.135}s`,
          }}
          className={`absolute left-1/2 top-0 -ml-[.8px] h-[5px] w-[1.6px] rounded-sm animate-v-tick ${
            light ? "bg-white" : "bg-v-fg"
          }`}
        />
      ))}
    </span>
  );
}
