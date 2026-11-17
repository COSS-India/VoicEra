# Self-hosted fonts

Vendored as `.woff2` so `next build` inside Docker does not call Google Fonts
(`next/font/google` fails offline with a cryptic null parse error).

Sources (Fontsource / OFL):

- Plus Jakarta Sans — `@fontsource/plus-jakarta-sans`
- IBM Plex Mono — `@fontsource/ibm-plex-mono`
- Noto Sans Kannada / Devanagari / Tamil — `@fontsource/noto-sans-*`
