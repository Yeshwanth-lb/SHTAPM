# Self-hosted fonts — Geist & Geist Mono

**License:** SIL Open Font License 1.1 (OFL). Free to bundle/self-host.

**Rule:** fonts are served **from this repo's bundled assets only** — never from
a CDN or any external host (TRD §02.2 / §02.5 offline-demo rule). At runtime the
browser loads local `woff2` referenced by `../../styles/fonts.css`.

## Expected layout (binaries added in P5)
```
assets/fonts/
├── geist/Geist-Variable.woff2
└── geist-mono/GeistMono-Variable.woff2
```

## P0 status — foundation only
- The `@font-face` contract (`styles/fonts.css`) is fixed now.
- The **woff2 binaries are NOT yet vendored.** They are added when frontend
  dependencies are installed in P5 — either via an `@fontsource/*` package
  (pinned then, once the exact name/version is verifiable) or by committing the
  OFL woff2 directly here. Both are self-hosted; neither uses a CDN.
- Reason for deferral: the `@fontsource` package name/version could not be
  verified against the npm registry during P0 and must not be guessed.
