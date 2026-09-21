---

id: WEB-0005
title: the site is a static export; nothing server-renders
status: accepted
date: 2026-09-21
deciders: ["devin"]
scope: ["apps/web/**", "scripts/e2e.sh", "infra/docker/Dockerfile.web"]
tags: ["nextjs", "cloudflare", "deployment", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["OPS-0001", "API-0001"]
confirmation: "cd apps/web && pnpm exec next build && test -d out"

---

# WEB-0005 — the site is a static export; nothing server-renders

## Context and Problem Statement

The landing page fetched initial state in `force-dynamic` SSR. On Cloudflare
Workers there is no Next.js server to do that fetch — the choice is between
running a Next runtime on Workers (OpenNext) and shipping a directory of
files. A dashboard whose data is stale within seconds gains nothing from SSR:
the hero subscribes to `/stream` and the dashboard repolls `/state` regardless.

## Considered Options

- **OpenNext on Workers.** Keeps SSR, adds a Node-compat runtime to debug and
  a Worker→Fly fetch on every page load for data that is already old.
- **Static export + client fetch.** Taken: `out/` is served by Workers static
  assets, and any static server can host the same artifact for self-hosting.

## Decision Outcome

`next.config.ts` sets `output: "export"`. `page.tsx` renders a static shell;
a client component fetches `fetchState`/`fetchLatestEvents` on mount and the
"API is not reachable" copy becomes a client-side state. `NEXT_PUBLIC_JEVE_API`
is inlined at build time, so changing it means rebuilding. `wrangler.toml` is
assets-only (`directory = "out"`, no `main`, no `binding`).

### Consequences

- Good: free-tier hosting, no per-request Worker→Fly hop, `wrangler deploy`
  is an asset upload.
- Bad: first paint shows a loading state instead of data; `next/image`,
  route handlers and `force-dynamic` are unavailable — adding any of them
  fails the build, which is the point.
- Reverse it if: the site ever needs per-request rendering (auth,
  personalisation); then OpenNext is the move, not a Node server.
