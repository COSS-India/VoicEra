"use client";

import { Button } from "@/components/ui/Button";
import { Select } from "@/components/ui/Select";
import { todayIso, type DatePreset } from "@/lib/history-filters";

const dateInputClass =
  "h-9 rounded-v-lg border border-v-line-strong bg-white px-3.5 text-xs text-v-fg transition-colors duration-[120ms] hover:border-v-accent focus:border-v-accent focus:outline-none";

interface HistoryDateFilterProps {
  preset: DatePreset;
  draftFrom: string;
  draftTo: string;
  canApply: boolean;
  onPresetChange: (preset: DatePreset) => void;
  onDraftFromChange: (from: string) => void;
  onDraftToChange: (to: string) => void;
  onApply: () => void;
}

/** Date preset + custom from/to drafts. Filtering only happens after Apply. */
export function HistoryDateFilter({
  preset,
  draftFrom,
  draftTo,
  canApply,
  onPresetChange,
  onDraftFromChange,
  onDraftToChange,
  onApply,
}: HistoryDateFilterProps) {
  const max = todayIso();

  return (
    <div className="flex shrink-0 flex-wrap items-center gap-2">
      <span className="text-[13px] font-medium text-v-body">Date</span>
      <Select
        size="sm"
        aria-label="Date range"
        className="!h-9 !py-0"
        value={preset}
        onChange={(e) => onPresetChange(e.target.value as DatePreset)}
      >
        <option value="all">All time</option>
        <option value="today">Today</option>
        <option value="7d">Last 7 days</option>
        <option value="30d">Last 30 days</option>
        <option value="custom">Custom range</option>
      </Select>
      {preset === "custom" ? (
        <>
          <input
            type="date"
            aria-label="From date"
            value={draftFrom}
            max={draftTo || max}
            onChange={(e) => onDraftFromChange(e.target.value)}
            className={dateInputClass}
          />
          <span className="text-xs text-v-muted">to</span>
          <input
            type="date"
            aria-label="To date"
            value={draftTo}
            min={draftFrom || undefined}
            max={max}
            onChange={(e) => onDraftToChange(e.target.value)}
            className={dateInputClass}
          />
          <Button size="sm" disabled={!canApply} onClick={onApply}>
            Apply
          </Button>
        </>
      ) : null}
    </div>
  );
}
