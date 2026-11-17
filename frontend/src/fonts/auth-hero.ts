import localFont from "next/font/local";

/** Indic demo fonts for the auth hero — self-hosted for offline Docker builds. */
export const notoKannada = localFont({
  src: [
    {
      path: "./noto-kannada/noto-sans-kannada-kannada-400-normal.woff2",
      weight: "400",
      style: "normal",
    },
    {
      path: "./noto-kannada/noto-sans-kannada-kannada-600-normal.woff2",
      weight: "600",
      style: "normal",
    },
  ],
  variable: "--font-kannada",
  display: "swap",
});

export const notoDevanagari = localFont({
  src: [
    {
      path: "./noto-devanagari/noto-sans-devanagari-devanagari-400-normal.woff2",
      weight: "400",
      style: "normal",
    },
    {
      path: "./noto-devanagari/noto-sans-devanagari-devanagari-600-normal.woff2",
      weight: "600",
      style: "normal",
    },
  ],
  variable: "--font-devanagari",
  display: "swap",
});

export const notoTamil = localFont({
  src: [
    {
      path: "./noto-tamil/noto-sans-tamil-tamil-400-normal.woff2",
      weight: "400",
      style: "normal",
    },
    {
      path: "./noto-tamil/noto-sans-tamil-tamil-600-normal.woff2",
      weight: "600",
      style: "normal",
    },
  ],
  variable: "--font-tamil",
  display: "swap",
});
