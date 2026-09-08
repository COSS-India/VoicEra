"use client";

import { useMemo, useState } from "react";
import * as d3 from "d3";
import { LANGS_GEO, langTotal } from "@/lib/dashboard-data";

export function Languages() {
  const [pick, setPick] = useState(0);

  const radius = useMemo(
    () => d3.scaleSqrt().domain([0, 21]).range([5, 30]),
    []
  );
  const color = useMemo(
    () =>
      d3
        .scaleLinear<string>()
        .domain([0, 9, 21])
        .range(["#dbeafe", "#3b82f6", "#1e40af"]),
    []
  );

  const active = LANGS_GEO[pick];

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <h1 className="text-3xl font-semibold tracking-tight">Where the calls are spoken</h1>
          <p className="max-w-[62ch] text-sm font-light leading-relaxed text-v-muted">
            Eleven languages across nine numbers. Hover or tap a marker to see its share, its
            dialect notes and which agents answer there.
          </p>
        </div>
        <div className="flex gap-6">
          <span className="flex flex-col gap-1">
            <span className="text-2xl font-semibold tracking-tight tabular-nums">{langTotal}</span>
            <span className="font-mono text-[9.5px] uppercase tracking-[.14em] text-v-muted">
              Calls this week
            </span>
          </span>
          <span className="flex flex-col gap-1">
            <span className="text-2xl font-semibold tracking-tight">11</span>
            <span className="font-mono text-[9.5px] uppercase tracking-[.14em] text-v-muted">
              Languages
            </span>
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 items-start gap-3.5 lg:grid-cols-[1.1fr_1fr]">
        <div className="flex flex-col gap-3 rounded-v-md border border-v-line bg-white p-5">
          <span className="font-mono text-[9.5px] uppercase tracking-[.16em] text-v-muted">
            Share of calls by state (approximate)
          </span>
          <svg viewBox="0 0 100 100" className="w-full rounded-v-sm bg-v-soft" style={{ aspectRatio: "1/1" }}>
            {LANGS_GEO.map((l, i) => (
              <g
                key={l.lang}
                transform={`translate(${l.x} ${l.y})`}
                onClick={() => setPick(i)}
                className="cursor-pointer"
              >
                {pick === i ? (
                  <circle r={radius(l.pct) / 100 * 130} fill="none" stroke="#3b82f6" strokeWidth={0.5} opacity={0.5}>
                    <animate attributeName="r" values={`${radius(l.pct) / 100 * 130};${radius(l.pct) / 100 * 130 * 1.5};${radius(l.pct) / 100 * 130}`} dur="2s" repeatCount="indefinite" />
                  </circle>
                ) : null}
                <circle
                  r={Math.max(1.6, radius(l.pct) / 8)}
                  fill={color(l.pct)}
                  stroke="#ffffff"
                  strokeWidth={0.4}
                />
                {pick === i ? (
                  <text x={0} y={-radius(l.pct) / 8 - 2} textAnchor="middle" fontSize={3} fill="#14121a" fontWeight={600}>
                    {l.lang}
                  </text>
                ) : null}
              </g>
            ))}
          </svg>
          <span className="text-xs font-light text-v-muted">
            Marker size and color scale with call share; positions are approximate.
          </span>
          <span className="flex items-center gap-2.5 pt-1">
            <span className="font-mono text-[9.5px] text-v-muted">Low</span>
            <span className="h-1.5 flex-1 rounded-full" style={{ background: "linear-gradient(90deg, #dbeafe, #3b82f6, #1e40af)" }} />
            <span className="font-mono text-[9.5px] text-v-muted">High</span>
          </span>
        </div>

        <div className="flex flex-col rounded-v-md border border-v-line bg-white">
          <div className="flex flex-col gap-1 border-b border-v-line px-5 py-4">
            <span className="text-[17px] font-semibold tracking-tight">
              {active.lang} · {active.where}
            </span>
            <span className="text-xs font-light text-v-muted">{active.note}</span>
          </div>
          <div className="flex max-h-96 flex-col overflow-y-auto">
            {LANGS_GEO.map((l, i) => (
              <button
                key={l.lang}
                onClick={() => setPick(i)}
                className={`flex cursor-pointer items-center justify-between gap-3 border-b border-v-line px-5 py-3 text-left last:border-0 ${
                  pick === i ? "bg-v-soft" : "hover:bg-v-soft/60"
                }`}
              >
                <span className="flex items-center gap-2.5 min-w-0">
                  <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: color(l.pct) }} />
                  <span className="flex min-w-0 flex-col text-left">
                    <span className="truncate text-[13.5px] font-medium">{l.lang}</span>
                    <span className="truncate text-[11.5px] font-light text-v-muted">{l.where}</span>
                  </span>
                </span>
                <span className="flex items-center gap-2.5 shrink-0">
                  <span className="block h-1 w-16 overflow-hidden rounded-full bg-v-line">
                    <span
                      className="block h-full rounded-full bg-v-accent"
                      style={{ width: `${(l.pct / 22) * 100}%` }}
                    />
                  </span>
                  <span className="w-10 text-right font-mono text-[11.5px] tabular-nums">{l.pct}%</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
