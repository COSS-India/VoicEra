"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { InfoTip } from "@/components/ui/Tooltip";
import { LanguageAddSearch } from "@/components/wizard/LanguageAddSearch";
import { LanguageCard } from "@/components/wizard/LanguageCard";
import { LanguageSwitchBar } from "@/components/wizard/LanguageSwitchBar";
import { ModelCard } from "@/components/wizard/ModelCard";
import type { StackEditorSection } from "@/components/wizard/LanguageStackEditor";
import { EMPTY_LANGUAGE_STACK, type LanguageStack } from "@/lib/language-stacks";
import type { WizardCatalogs } from "@/lib/use-wizard-catalogs";
import type { LanguagesMap } from "@/lib/catalog-types";

export interface LanguageConfigListProps {
  langs: string[];
  primaryLang: string;
  languageStacks: Record<string, LanguageStack>;
  activeLang: string;
  onLangsChange: (langs: string[]) => void;
  onPrimaryLangChange: (lang: string) => void;
  onActiveLangChange: (lang: string) => void;
  onStackChange: (lang: string, patch: Partial<LanguageStack>) => void;
  catalogs: WizardCatalogs;
  selectableLanguages: LanguagesMap;
  stackSections?: StackEditorSection[];
  allowMultipleExpanded?: boolean;
  disabled?: boolean;
}

/**
 * Language search, full cards when in view, compact fixed switch bar on scroll,
 * and model stack card for the active language.
 */
export function LanguageConfigList({
  langs,
  primaryLang,
  languageStacks,
  activeLang,
  onLangsChange,
  onPrimaryLangChange,
  onActiveLangChange,
  onStackChange,
  catalogs,
  selectableLanguages,
  stackSections = ["stt", "llm", "tts"],
  disabled,
}: LanguageConfigListProps) {
  const resolvedPrimary = langs.includes(primaryLang) ? primaryLang : (langs[0] ?? "");
  const prevLangCountRef = useRef(langs.length);
  const cardsRef = useRef<HTMLDivElement>(null);
  const [compactBar, setCompactBar] = useState(false);
  const [barBox, setBarBox] = useState({ top: 0, left: 0, width: 0 });
  const editingLang = langs.includes(activeLang) ? activeLang : resolvedPrimary;
  const activeStack = languageStacks[editingLang] ?? EMPTY_LANGUAGE_STACK;
  const showCompactBar = compactBar && langs.length > 1;

  useEffect(() => {
    const prev = prevLangCountRef.current;
    prevLangCountRef.current = langs.length;

    if (langs.length === 0) return;

    if (langs.length === 1 && langs[0] && activeLang !== langs[0]) {
      onActiveLangChange(langs[0]);
      return;
    }

    if (!langs.includes(activeLang)) {
      onActiveLangChange(resolvedPrimary);
      return;
    }

    if (langs.length > prev) {
      const added = langs[langs.length - 1];
      if (added) onActiveLangChange(added);
    }
  }, [langs, activeLang, resolvedPrimary, onActiveLangChange]);

  useEffect(() => {
    const cards = cardsRef.current;
    if (!cards || langs.length < 2) {
      setCompactBar(false);
      return;
    }

    const scrollRoot =
      cards.closest("[data-wizard-scroll]") ?? cards.closest(".overflow-y-auto");

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry) setCompactBar(!entry.isIntersecting);
      },
      { root: scrollRoot, threshold: 0 },
    );

    observer.observe(cards);
    return () => observer.disconnect();
  }, [langs.length]);

  useEffect(() => {
    const cards = cardsRef.current;
    if (!cards) return;

    const scrollRoot = cards.closest("[data-wizard-scroll]") ?? cards.closest(".overflow-y-auto");

    const syncBarBox = () => {
      if (!scrollRoot) return;
      const scrollRect = scrollRoot.getBoundingClientRect();
      const nav = document.querySelector("[data-section-nav]");
      const navRect = nav?.getBoundingClientRect();
      setBarBox({
        top: scrollRect.top,
        left: navRect?.left ?? scrollRect.left,
        width: navRect?.width ?? scrollRect.width,
      });
    };

    syncBarBox();
    window.addEventListener("resize", syncBarBox);

    return () => {
      window.removeEventListener("resize", syncBarBox);
    };
  }, []);

  const selectLanguage = useCallback(
    (lang: string) => {
      if (lang !== activeLang) onActiveLangChange(lang);
    },
    [activeLang, onActiveLangChange],
  );

  const removeLanguage = useCallback(
    (lang: string) => {
      if (!langs.includes(lang)) return;
      onLangsChange(langs.filter((id) => id !== lang));
    },
    [langs, onLangsChange],
  );

  const addLanguage = useCallback(
    (id: string) => {
      if (langs.includes(id)) return;
      onLangsChange([...langs, id]);
    },
    [langs, onLangsChange],
  );

  const makePrimary = useCallback(
    (lang: string) => {
      if (lang === resolvedPrimary) return;
      onPrimaryLangChange(lang);
    },
    [resolvedPrimary, onPrimaryLangChange],
  );

  return (
    <section className="flex flex-col gap-4 rounded-v-md border border-v-line bg-white p-5">
      {langs.length > 1 ? (
        <div
          className={[
            "fixed z-30 overflow-hidden border-b border-v-line bg-white/95 shadow-[0_2px_8px_rgba(11,11,12,0.06)] backdrop-blur-md transition-[transform,opacity] duration-300 ease-[cubic-bezier(0.4,0,0.2,1)] supports-[backdrop-filter]:bg-white/90",
            showCompactBar
              ? "translate-y-0 opacity-100"
              : "pointer-events-none -translate-y-full opacity-0",
          ].join(" ")}
          style={{ top: barBox.top, left: barBox.left, width: barBox.width }}
          data-testid="language-compact-bar"
        >
          <div className="w-full px-[34px] py-2">
            <LanguageSwitchBar
              langs={langs}
              primaryLang={resolvedPrimary}
              activeLang={editingLang}
              languages={catalogs.languages}
              onSelect={selectLanguage}
              onMakePrimary={makePrimary}
              disabled={disabled}
            />
          </div>
        </div>
      ) : null}

      <header className="flex items-center gap-2">
        <span className="text-[14.5px] font-semibold">Languages</span>
        <InfoTip text="The primary language opens the call. Each language keeps its own STT, TTS, and LLM when switching mid-call." />
      </header>

      <LanguageAddSearch
        languages={selectableLanguages}
        selected={langs}
        onAdd={addLanguage}
        disabled={!!disabled || !!catalogs.loading || !!catalogs.languagesLoading}
      />

      {langs.length === 0 ? (
        <p className="text-sm font-light text-v-muted">
          Pick at least one language. Tap the crown on a badge to set it as primary.
        </p>
      ) : null}

      {langs.length > 0 ? (
        <>
          <div ref={cardsRef} className="border-b border-v-line pb-3.5" data-testid="language-badge-bar">
            <p className="mb-2.5 text-[11px] font-medium uppercase tracking-[.12em] text-v-muted">
              Settings for
              {langs.length > 1 ? (
                <span className="ml-1.5 font-normal normal-case tracking-normal text-v-muted">
                  — tap a language to edit its stack
                </span>
              ) : null}
            </p>
            <div className="flex flex-wrap gap-2.5" role="tablist" aria-label="Configured languages">
              {langs.map((lang) => (
                <LanguageCard
                  key={lang}
                  lang={lang}
                  isPrimary={lang === resolvedPrimary}
                  selected={lang === editingLang}
                  onSelect={() => selectLanguage(lang)}
                  onMakePrimary={() => makePrimary(lang)}
                  onRemove={() => removeLanguage(lang)}
                  languages={catalogs.languages}
                  disabled={disabled}
                />
              ))}
            </div>
          </div>

          {editingLang ? (
            <ModelCard
              lang={editingLang}
              stack={activeStack}
              catalogs={catalogs}
              onStackChange={(patch) => onStackChange(editingLang, patch)}
              sections={stackSections}
              catalogsLoading={catalogs.loading && activeLang === editingLang}
            />
          ) : null}
        </>
      ) : null}

      {!catalogs.loading && !catalogs.languagesLoading && Object.keys(selectableLanguages).length === 0 ? (
        <p className="text-xs font-light text-v-muted">
          No configured STT/TTS provider declares language support — add one under Integrations first.
        </p>
      ) : null}
    </section>
  );
}
