---

id: WEB-0006
title: UI components are shadcn on Base UI primitives over the app palette
status: accepted
date: 2026-09-21
deciders: ["claude"]
scope: ["apps/web/src/components/**", "apps/web/src/app/globals.css", "apps/web/src/app/layout.tsx", "apps/web/components.json", "apps/web/postcss.config.mjs", "apps/web/package.json"]
tags: ["ui", "dependencies", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["WEB-0005"]
confirmation: "pnpm --filter @jeve/web exec tsc --noEmit && cd apps/web && pnpm exec next build && test -d out"

---

# WEB-0006 — UI components are shadcn on Base UI primitives over the app palette

## Context and Problem Statement

The app's panels, filters, and controls were hand-rolled: a `<select>`, bespoke
pill chips, plain `<table>`s, and one-off `.panel`/`.pill`/`.chip` classes. Each
new screen re-invented focus management, keyboard interaction, and ARIA. The
project asked for shadcn — with Base UI (`@base-ui/react`) under the primitives
instead of Radix — and for vendored registries (obsidianui.dev, rareui.com)
where a component genuinely fits.

## Considered Options

* shadcn with the Base UI preset, vendored into `src/components/ui/`, app vars
  aliased onto shadcn tokens.
* shadcn on Radix — rejected: the task called for Base UI, whose `render` prop
  composes cleanly with the app's buttons.
* Rewriting the palette to stock shadcn tokens — rejected: it would fork the
  design language; aliasing keeps one source of truth.
* More registry components (rareui navs/orbs, obsidian cursors/grids) —
  rejected: ornamental; none solved a real UI gap the way the loader does.

## Decision Outcome

The component layer is **shadcn (Base UI preset, nova style), vendored into
`src/components/ui/`**, with the app's palette kept as the single token source:

* `globals.css` maps the app's CSS variables onto shadcn tokens
  (`--background: var(--bg)`, `--card: var(--panel)`, `--primary: var(--mark)`,
  etc.) instead of adopting a shadcn palette — the renderer and custom classes
  keep reading the same vars, and Tailwind utilities inherit the identity.
* The `--muted` collision (shadcn uses it for surfaces; the app used it for
  text) resolves the shadcn way: `--muted` is the surface, text is
  `--muted-foreground`, and `.muted` points at the foreground token.
* App-specific classes that are the design language (`.ev` timeline cells,
  `.dist-*` bars, `.dash-grid`, `.strip`, `.lane`, `.world-*`) are kept —
  shadcn replaces generic chrome, not the app's own vocabulary. `.grid` was
  renamed to `.dash-grid` because Tailwind claims `grid`.
* Primitives in use: `card`, `badge`, `button`, `select`, `dropdown-menu`
  (the kind filter's checkbox dropdown), `toggle-group` (the kind chips —
  `aria-pressed` keeps the e2e contract), `table`, `progress`, `scroll-area`,
  `tooltip`, `sonner` toasts.
* The obsidianui.dev registry contributes one block, `jelly-loader` (the
  world-loading state), recolored onto the app's grey-to-`--mark` ramp.
  rareui.com's catalogue is display/ornament components; nothing fit this ops
  console.
* `next/font/google` (Geist) was not adopted: the identity is monospace and a
  font fetch at build time would make offline builds fragile.

### Consequences

* e2e's `person-select` driver is a Base UI listbox (`role=option`), not a
  `<select>` — the spec clicks the trigger and picks the option by name.
* New dependencies: `@base-ui/react`, `tailwindcss` v4 (with
  `@tailwindcss/postcss` and `tw-animate-css`), `sonner`, `next-themes`,
  `class-variance-authority`, `cn`, `lucide-react`, `motion` (jelly-loader),
  `shadcn` (dev-time CLI).
* `components.json` is the registry entry point; adding a component is
  `pnpm dlx shadcn add <name-or-url>`.
