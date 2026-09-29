"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Crown } from "lucide-react";
import { Tooltip } from "@/components/ui/Tooltip";
import type { LanguagesMap } from "@/lib/catalog-types";
import { languageLabel } from "@/lib/use-wizard-catalogs";

export interface LanguageSwitchBarProps {
  langs: string[];
  primaryLang: string;
  activeLang: string;
  languages: LanguagesMap;
  onSelect: (lang: string) => void;
  onMakePrimary: (lang: string) => void;
  disabled?: boolean;
}

/** Compact centered language switcher — pills grow from the middle, scroll when needed. */
export function LanguageSwitchBar({
  langs,
  primaryLang,
  activeLang,
  languages,
  onSelect,
  onMakePrimary,
  disabled,
}: LanguageSwitchBarProps) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [fadeLeft, setFadeLeft] = useState(false);
  const [fadeRight, setFadeRight] = useState(false);

  const syncScrollFades = useCallback(() => {
    const track = trackRef.current;
    if (!track) return;
    const { scrollLeft, scrollWidth, clientWidth } = track;
    setFadeLeft(scrollLeft > 4);
    setFadeRight(scrollLeft + clientWidth < scrollWidth - 4);
  }, []);

  useEffect(() => {
    syncScrollFades();
    const track = trackRef.current;
    if (!track) return;

    track.addEventListener("scroll", syncScrollFades, { passive: true });
    window.addEventListener("resize", syncScrollFades);

    const observer = new ResizeObserver(syncScrollFades);
    observer.observe(track);

    return () => {
      track.removeEventListener("scroll", syncScrollFades);
      window.removeEventListener("resize", syncScrollFades);
      observer.disconnect();
    };
  }, [langs, syncScrollFades]);

  useEffect(() => {
    const track = trackRef.current;
    const active = track?.querySelector<HTMLElement>(`[data-lang="${activeLang}"]`);
    if (!track || !active) return;

    const target =
      active.offsetLeft - track.clientWidth / 2 + active.offsetWidth / 2;

    track.scrollTo({ left: Math.max(0, target), behavior: "smooth" });
  }, [activeLang, langs]);

  return (
    <div className="relative min-w-0" data-testid="language-switch-bar">
      <div
        className={[
          "pointer-events-none absolute inset-y-0 left-0 z-10 w-10 bg-gradient-to-r from-white via-white/80 to-transparent transition-opacity duration-300",
          fadeLeft ? "opacity-100" : "opacity-0",
        ].join(" ")}
        aria-hidden
      />
      <div
        className={[
          "pointer-events-none absolute inset-y-0 right-0 z-10 w-10 bg-gradient-to-l from-white via-white/80 to-transparent transition-opacity duration-300",
          fadeRight ? "opacity-100" : "opacity-0",
        ].join(" ")}
        aria-hidden
      />

      <div
        ref={trackRef}
        className="scrollbar-hide overflow-x-auto scroll-smooth"
        role="tablist"
        aria-label="Switch language"
      >
        <div className="mx-auto flex w-max min-w-full items-center justify-center gap-1.5 px-2 py-0.5">
          {langs.map((lang) => {
            const label = languageLabel(languages, lang) || lang;
            const isPrimary = lang === primaryLang;
            const selected = lang === activeLang;

            return (
              <div
                key={lang}
                data-lang={lang}
                className={[
                  "inline-flex shrink-0 items-center gap-1 rounded-full border transition-all duration-200 ease-out",
                  selected
                    ? "border-v-line-strong bg-v-soft py-0.5 pl-0.5 pr-2 shadow-[0_1px_2px_rgba(11,11,12,0.05)]"
                    : "border-transparent bg-transparent py-0.5 pl-0.5 pr-2 hover:border-v-line hover:bg-white",
                ].join(" ")}
              >
                {isPrimary ? (
                  <Tooltip text="Primary language">
                    <span
                      className="flex size-5 shrink-0 items-center justify-center rounded-full bg-v-accent text-white"
                      aria-label="Primary language"
                    >
                      <Crown className="size-2.5" strokeWidth={1.75} />
                    </span>
                  </Tooltip>
                ) : (
                  <Tooltip text="Set as primary language">
                    <button
                      type="button"
                      disabled={disabled}
                      onClick={() => onMakePrimary(lang)}
                      className="flex size-5 shrink-0 cursor-pointer items-center justify-center rounded-full text-v-muted transition-colors hover:bg-v-soft hover:text-v-fg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-v-line-strong disabled:opacity-40"
                      aria-label={`Set ${label} as primary`}
                    >
                      <Crown className="size-2.5" strokeWidth={1.75} />
                    </button>
                  </Tooltip>
                )}
                <button
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  aria-controls={`language-stack-${lang}`}
                  disabled={disabled}
                  onClick={() => onSelect(lang)}
                  className={[
                    "cursor-pointer whitespace-nowrap px-0.5 text-[12.5px] font-medium transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-v-line-strong disabled:cursor-not-allowed disabled:opacity-50",
                    selected ? "text-v-fg" : "text-v-muted-2 hover:text-v-fg",
                  ].join(" ")}
                >
                  {label}
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
