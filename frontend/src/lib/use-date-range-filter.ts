"use client";

import { useCallback, useState } from "react";
import {
  getDatePresetValue,
  isCompleteRange,
  isoDate,
  rangeFromInputs,
  type DatePreset,
  type DateRangeValue,
} from "@/lib/history-filters";

const EMPTY: DateRangeValue = { from: null, to: null };

/**
 * Dograh-style draft vs applied date filter.
 * - `draftFrom` / `draftTo` are what the inputs show (never filter by themselves)
 * - `applied` is what the table uses (only updated by presets or Apply)
 * - Apply always commits + returns true so the page can re-fetch (even on re-apply)
 */
export function useDateRangeFilter() {
  const [preset, setPreset] = useState<DatePreset>("all");
  const [draftFrom, setDraftFrom] = useState("");
  const [draftTo, setDraftTo] = useState("");
  const [applied, setApplied] = useState<DateRangeValue>(EMPTY);

  const hasDateFilter = isCompleteRange(applied);
  const draftRange = rangeFromInputs(draftFrom, draftTo);
  const canApply = isCompleteRange(draftRange);

  const syncDraftFromApplied = useCallback((range: DateRangeValue) => {
    setDraftFrom(range.from ? isoDate(range.from) : "");
    setDraftTo(range.to ? isoDate(range.to) : "");
  }, []);

  const selectPreset = useCallback(
    (next: DatePreset) => {
      setPreset(next);
      if (next === "custom") {
        // Keep applied as-is until Apply; seed inputs from current applied.
        syncDraftFromApplied(applied);
        return { applied: null as DateRangeValue | null, shouldReload: false };
      }
      if (next === "all") {
        setApplied(EMPTY);
        setDraftFrom("");
        setDraftTo("");
        return { applied: EMPTY, shouldReload: true };
      }
      const range = getDatePresetValue(next);
      setApplied(range);
      syncDraftFromApplied(range);
      return { applied: range, shouldReload: true };
    },
    [applied, syncDraftFromApplied],
  );

  /** Commit draft → applied. Always returns the new range when valid so caller can reload. */
  const applyCustom = useCallback(() => {
    const range = rangeFromInputs(draftFrom, draftTo);
    if (!isCompleteRange(range)) return null;
    setPreset("custom");
    setApplied(range);
    syncDraftFromApplied(range);
    return range;
  }, [draftFrom, draftTo, syncDraftFromApplied]);

  return {
    preset,
    draftFrom,
    draftTo,
    setDraftFrom,
    setDraftTo,
    applied: hasDateFilter ? applied : null,
    hasDateFilter,
    canApply,
    selectPreset,
    applyCustom,
  };
}
