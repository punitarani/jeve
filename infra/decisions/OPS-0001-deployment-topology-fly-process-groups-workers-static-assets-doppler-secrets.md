---

id: OPS-0001
title: deployment topology — fly process groups, workers static assets, doppler secrets
status: accepted
date: 2026-09-21
deciders: ["devin"]
scope: ["infra/**", "fly.toml", "docker-compose.prod.yml", "apps/web/wrangler.toml", ".github/workflows/ci.yml", "Makefile"]
tags: ["deployment", "fly", "cloudflare", "doppler", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["LLM-0007", "SIM-0003", "WEB-0005", "GEN-0001"]
confirmation: "python3 scripts/check_fly_config.py"

---

# OPS-0001 — deployment topology: fly process groups, workers static assets, doppler secrets

## Context and Problem Statement

The deploy shape was written twice and disagreed with itself: env examples
described Fly + Doppler + an external Postgres, a compose file described one
VM, and the committed `fly.toml`/`wrangler.toml` carried placeholders that
could not work (a `.next` directory is not a servable site; a DSN in `[env]`
is not a secret; a `sim` group defaulting to `--calls replay` halts on its
first cache miss). Somebody had to pick one shape and make the files true.

## Considered Options

- **Two Fly apps, api and sim.** Rejected: one image, one secrets set, one
  deploy — two apps buy isolation nothing here needs.
- **Next.js server-side on Workers (OpenNext).** Rejected — see WEB-0005.
- **One Fly app, `[processes]` api + sim; static export on Workers; Doppler
  for secrets.** Taken.

## Decision Outcome

`fly.toml` is one app `jeve-backend` with process groups `api` (the only
ingress, on `JEVE_DATABASE_POOLED_URL` when set, else the direct DSN) and
`sim` (`sim-entrypoint.sh`, `on-failure` restarts, no service). The web app
is an assets-only Worker serving `out/`. Secrets live in Doppler projects
`app`/`infra`/`worker` and land as Fly secrets and GitHub secrets; the sim's
Postgres URL must be a *direct* connection because the writer lock is a
session-level advisory lock. The frontend is read-only, so the dialogue
endpoint's spend path is off in production (`JEVE_DIALOGUE_GENERATE=off`).

### Consequences

- Good: one image, one `fly deploy`, no SSR hop, no spend surface from the
  browser.
- Bad: per-group env differences live in command prefixes, which is ugly but
  visible.
- Reverse it if: the sim ever needs to scale — it is pinned single-writer by
  the advisory lock anyway.
