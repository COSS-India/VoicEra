"use client";

import { useState } from "react";

/**
 * The animated "V" mark used on the sign-in page's hero panel — a rounded
 * bracket that morphs into a checkmark tick on hover. Uses `currentColor`
 * (the hero renders it white-on-blue; the sidebar renders it dark-on-white)
 * so both places share this exact same mark/animation, not a lookalike.
 */
export function LogoMark({ size = 42, className = "" }: { size?: number; className?: string }) {
  const [hover, setHover] = useState(false);
  const [touched, setTouched] = useState(false);

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 48 48"
      fill="none"
      aria-label="Voicera"
      className={className}
      onMouseEnter={() => {
        setHover(true);
        setTouched(true);
      }}
      onMouseLeave={() => setHover(false)}
    >
      <rect
        x="15"
        y="5"
        width="18"
        height="22"
        rx="9"
        stroke="currentColor"
        strokeWidth="2.6"
        fill="none"
        className="transition-all duration-500"
        style={{ opacity: touched && hover ? 0 : 1 }}
      />
      <g className="transition-opacity duration-300" style={{ opacity: touched && hover ? 0 : 1 }}>
        <path
          d="M18.8 26 L20.9 40.4 Q21.1 43 23.4 43 H24.6 Q26.9 43 27.1 40.4 L29.2 26 Z"
          stroke="currentColor"
          strokeWidth="2.6"
          fill="none"
        />
      </g>
      <path
        d={hover ? "M9 8 L24 39 L39 8" : "M19.9 12.4 L24 20.6 L28.1 12.4"}
        stroke="currentColor"
        strokeWidth={hover ? 5.5 : 3}
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
        className="transition-all duration-500"
      />
    </svg>
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
