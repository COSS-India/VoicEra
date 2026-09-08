"use client";

import { useEffect, useState } from "react";
import { Noto_Sans_Kannada, Noto_Sans_Devanagari, Noto_Sans_Tamil } from "next/font/google";
import { LogoMark } from "@/components/ui/VoicEraMark";

const notoKannada = Noto_Sans_Kannada({
  subsets: ["kannada"],
  weight: ["400", "600"],
  variable: "--font-kannada",
});
const notoDevanagari = Noto_Sans_Devanagari({
  subsets: ["devanagari"],
  weight: ["400", "600"],
  variable: "--font-devanagari",
});
const notoTamil = Noto_Sans_Tamil({
  subsets: ["tamil"],
  weight: ["400", "600"],
  variable: "--font-tamil",
});

interface Turn {
  text: string;
  gloss: string;
}

interface Lang {
  label: string;
  fontClass: string;
  turns: Turn[];
}

const LANGS: Lang[] = [
  {
    label: "ಕನ್ನಡ · Kannada",
    fontClass: notoKannada.className,
    turns: [
      { text: "ಇಂದಿನ ಟೊಮೇಟೊ ಮಂಡಿ ದರ ಎಷ್ಟು?", gloss: "What is today's tomato mandi rate?" },
      { text: "ಬೆಳಗಾವಿ ಎಪಿಎಂಸಿಯಲ್ಲಿ ಕ್ವಿಂಟಲ್‌ಗೆ ₹1,850.", gloss: "₹1,850 per quintal at Belagavi APMC." },
    ],
  },
  {
    label: "हिन्दी · Hindi",
    fontClass: notoDevanagari.className,
    turns: [
      { text: "मेरी फसल के पत्ते पीले हो रहे हैं।", gloss: "The leaves of my crop are turning yellow." },
      { text: "यह नाइट्रोजन की कमी है — उपाय बताता हूँ।", gloss: "That is nitrogen deficiency — here is what to do." },
    ],
  },
  {
    label: "தமிழ் · Tamil",
    fontClass: notoTamil.className,
    turns: [
      { text: "எனது ஓய்வூதியம் இன்னும் வரவில்லை.", gloss: "My pension has not arrived yet." },
      { text: "பத்து வேலை நாட்களுக்குள் வரும்.", gloss: "It will arrive within ten working days." },
    ],
  },
];

export function AuthHero() {
  const [langIndex, setLangIndex] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setLangIndex((i) => (i + 1) % LANGS.length), 4200);
    return () => clearInterval(id);
  }, []);

  const lang = LANGS[langIndex];

  return (
    <div className="relative flex flex-col justify-between gap-7 overflow-hidden bg-[linear-gradient(152deg,#14121a_0%,#1e40af_58%,#3b82f6_100%)] bg-[length:220%_220%] px-6 py-8 text-white animate-v-grad sm:px-10 sm:py-10">
      <span className="pointer-events-none absolute -right-[280px] -top-[220px] h-[720px] w-[720px] animate-v-drift rounded-full bg-[radial-gradient(circle,rgba(59,130,246,.42)_0%,rgba(59,130,246,0)_68%)]" />
      <span className="pointer-events-none absolute -bottom-[240px] -left-[200px] h-[560px] w-[560px] animate-v-drift-rev rounded-full bg-[radial-gradient(circle,rgba(20,18,26,.62)_0%,rgba(20,18,26,0)_70%)]" />

      <div className="relative inline-flex w-fit cursor-pointer items-center gap-3 text-white">
        <LogoMark size={42} />
        <span className="text-[23px] font-semibold tracking-tight">VoicEra</span>
      </div>

      <div className="relative flex min-h-0 min-w-0 max-w-[34ch] flex-col gap-6 sm:gap-7">
        <h1 className="m-0 text-[clamp(30px,3.6vw,54px)] font-semibold leading-[1.03] tracking-tight text-balance">
          A phone call, in any language, is enough.
        </h1>

        <div className="flex min-w-0 flex-col gap-4">
          <div className="flex items-center gap-2.5">
            <span className="h-[7px] w-[7px] animate-v-live rounded-full bg-white" />
            <span className="font-mono text-[10.5px] uppercase tracking-[.16em] text-white/60">
              {lang.label}
            </span>
          </div>
          <div className="flex items-start gap-4.5">
            <span className="flex h-[60px] w-11 shrink-0 items-center gap-1">
              {[0, 0.12, 0.24, 0.36, 0.48].map((delay, i) => (
                <span
                  key={i}
                  style={{ animationDelay: `${delay}s` }}
                  className={`h-full w-[3px] origin-center animate-v-bar rounded-sm ${
                    i === 2 ? "bg-white" : "bg-white/55"
                  }`}
                />
              ))}
            </span>
            <div className="flex min-w-0 flex-1 flex-col gap-3.5">
              {lang.turns.map((turn, i) => (
                <div key={`${langIndex}-${i}`} className="flex animate-v-turn-in flex-col gap-1">
                  <span className={`text-xl leading-snug text-white ${lang.fontClass}`}>
                    {turn.text}
                  </span>
                  <span className="text-[13px] font-light leading-snug text-white/60">
                    {turn.gloss}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="relative flex flex-wrap items-center gap-5 text-xs font-light">
        {["Repository", "Docs", "Privacy", "Terms"].map((l) => (
          <a key={l} href="#" className="text-white/72 hover:text-white">
            {l}
          </a>
        ))}
      </div>
    </div>
  );
}
