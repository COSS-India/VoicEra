/**
 * Brand mark used on the sign-in hero and app sidebar.
 * Shared asset: /public/voicera-logo.png
 */
export function LogoMark({ size = 42, className = "" }: { size?: number; className?: string }) {
  return (
    // eslint-disable-next-line @next/next/no-img-element -- static public brand asset
    <img
      src="/voicera-logo.png"
      alt="VoicEra"
      width={size}
      height={size}
      className={`shrink-0 object-contain ${className}`.trim()}
      draggable={false}
    />
  );
}

export function VoicEraMark({
  size = 22,
  className = "",
}: {
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 28 28"
      fill="none"
      aria-hidden
      className={className}
    >
      <g stroke="currentColor" strokeWidth="2.1" strokeLinecap="round">
        <path d="M3 8 V20" />
        <path d="M7.5 4.5 V23.5" />
        <path d="M12 8.5 V19.5" />
      </g>
      <g stroke="var(--v-accent)" strokeWidth="2.1" strokeLinecap="round">
        <path d="M16.5 10.5 V17.5" />
        <path d="M21 12 V16" />
        <path d="M25 13.2 V14.8" />
      </g>
    </svg>
  );
}

export function AgentWaveIcon({ className = "" }: { className?: string }) {
  return (
    <span
      className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-v-fg text-white ${className}`}
    >
      <svg width="16" height="16" viewBox="0 0 28 28" fill="none" aria-hidden>
        <g stroke="white" strokeWidth="2.4" strokeLinecap="round">
          <path d="M3 8 V20" />
          <path d="M7.5 4.5 V23.5" />
          <path d="M12 8.5 V19.5" />
          <path d="M16.5 10.5 V17.5" />
          <path d="M21 12 V16" />
          <path d="M25 13.2 V14.8" />
        </g>
      </svg>
    </span>
  );
}
