import type { Metadata } from "next";
import { Plus_Jakarta_Sans, IBM_Plex_Mono } from "next/font/google";
import "./globals.css";

const jakarta = Plus_Jakarta_Sans({
  variable: "--font-jakarta",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
});

const ibmPlexMono = IBM_Plex_Mono({
  variable: "--font-ibm-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500"],
});

// Origin Trial tokens for Chrome's built-in Translator API and Language
// Detection API (used by src/lib/chrome-translation.ts for free, on-device
// call-transcript translation). Each is registered per-domain at
// https://developer.chrome.com/origintrials/ and expires — without a valid
// token here, the on-device API silently reports unavailable for every
// visitor (no error) and every translate request falls back to the paid
// LLM backend endpoint. Set both env vars once tokens are issued; renew
// before expiry to avoid a silent cost/latency regression.
//
// Rendered as raw <meta http-equiv="origin-trial"> tags rather than via the
// `metadata.other` API: Chrome only honors this token through `http-equiv`
// (or a response header), and Next's `Metadata.other` field always renders
// plain `name="..."` attributes with no way to set `http-equiv` — using it
// here would silently produce a tag Chrome ignores.
function getOriginTrialTokens(): string[] {
  return [
    process.env.NEXT_PUBLIC_TRANSLATOR_ORIGIN_TRIAL_TOKEN,
    process.env.NEXT_PUBLIC_LANGUAGE_DETECTOR_ORIGIN_TRIAL_TOKEN,
  ].filter((token): token is string => Boolean(token));
}

export const metadata: Metadata = {
  title: "VoicEra",
  description: "VoicEra",
  icons: {
    icon: "/voicera-logo.png",
  },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${jakarta.variable} ${ibmPlexMono.variable} h-full antialiased`}
    >
      <head>
        {getOriginTrialTokens().map((token) => (
          <meta key={token} httpEquiv="origin-trial" content={token} />
        ))}
      </head>
      <body className="min-h-full flex flex-col font-sans">{children}</body>
    </html>
  );
}
