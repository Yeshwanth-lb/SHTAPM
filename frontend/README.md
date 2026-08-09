# frontend/ — Aurora admin dashboard (React + Vite + TS)

**P0 status: tooling + font foundation only.** No application code yet.

Present now (P0):
- Build/lint/test toolchain: Vite 5, TypeScript 5.4, Vitest, ESLint (flat),
  Prettier — configs + one placeholder test.
- Self-hosted font foundation: `src/styles/fonts.css` + `src/assets/fonts/`
  (Geist / Geist Mono, OFL, no CDN — see `src/assets/fonts/FONTS.md`).
- Directory skeleton per TRD §02.6 (`pages/`, `components/{charts,panels,ui,aurora}/`,
  `features/`, `hooks/`, `store/`, `api/`, `lib/`, `styles/`, `types/`).

Added in **P5** (not now): React 18.2, React Router 6, Zustand, TanStack Query,
uPlot, ECharts, Framer Motion, Tailwind + Aurora tokens (Doc04), shadcn/Radix,
the `package-lock.json`, and the actual pages/components. The `frontend` compose
service is gated behind the `app` profile until then.
