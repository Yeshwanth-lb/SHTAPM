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

## Status — vendored 2026-09-24

The woff2 binaries are committed at the paths above. They were copied from
Vercel's official `geist` npm package, version **1.7.2** (`npm pack geist`,
files `dist/fonts/geist-sans/Geist-Variable.woff2` and
`dist/fonts/geist-mono/GeistMono-Variable.woff2`). The package's OFL licence
text is alongside as `OFL.txt`, as the OFL requires. No npm dependency was
added. Before this, every `@font-face` URL returned 404 and the dashboard
silently fell back to the system font. The AC10 audit found that, and
`edge/tests/test_ac10_repo_offline.py` now checks for it.
