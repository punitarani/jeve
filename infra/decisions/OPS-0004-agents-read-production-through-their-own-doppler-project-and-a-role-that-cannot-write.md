---
id: "OPS-0004"
title: "Agents read production through their own Doppler project and a role that cannot write"
status: "proposed"
date: 2026-09-23
deciders: ["punitarani", "claude"]
scope: [".claude/setup-cloud.sh", "docs/environment-variables.md"]
tags: ["deployment", "doppler", "agents", "security", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["OPS-0001", "LLM-0007"]
confirmation: null
---
# OPS-0004 — Agents read production through their own Doppler project and a role that cannot write

## Context and Problem Statement

A Claude Code cloud session has no browser and no Doppler login, so anything
it reads of production has to come from a token in its environment. The
obvious token, one for `worker/prd`, hands over `JEVE_DATABASE_URL` for
PlanetScale's app role, which holds `pg_write_all_data`, plus
`OPENROUTER_API_KEY`, which spends from the account production spends from.
The token is read-only on Doppler, but what it reads are write credentials.
It also hands over `JEVE_DATABASE_URL` under the name the whole test suite
obeys, and the suite TRUNCATEs, reseeds and drops `public`.

## Considered Options

- **A Doppler project `agent`, config `prd`, holding production's knobs and
  none of its credentials.** Taken.
- **A branch config `worker/prd_agents` that overrides every credential.**
  Rejected. It inherits every production knob for free, but it fails open:
  a credential added to `worker/prd` later reaches the agents unless someone
  remembers to override it.
- **A `worker/prd` token and a promise not to write.** Rejected. Nothing
  enforces it, and `make test` would be the first thing to break it.

## Decision Outcome

Agents read production through a token for `agent/prd`: its database URLs
name a role inheriting only `pg_read_all_data`, and its OpenRouter key is its
own, not production's.

A separate project fails closed. Its cost is that knobs are copied by hand,
and a hand copy is also how a credential gets in. So nothing is copied into
`agent/prd` from `worker` or `infra` whose name ends in `_KEY`, `_TOKEN` or
`_URL` with a password in it. The database URLs are the read-only role's,
set by hand from PlanetScale. The role, not the config, is what enforces
read-only: pointed at production's app role, `has_table_privilege` reports
26 writable tables; pointed at `agents_ro`, it must report none.

Cloud sessions reach the internet through an HTTP/HTTPS proxy, so the
Postgres wire protocol does not get out of them. There, production is read
through the PlanetScale connector or the public API. The `agent/prd` URLs
serve sessions that can reach Postgres.

### Consequences

- Good: a leaked cloud token exposes read access to simulated data, plus a
  model key whose spend is capped separately. `make test` pointed at
  production fails on its first INSERT rather than wiping the world.
- Bad: a production knob changed in `worker/prd` is not reflected here until
  it is copied. A role PlanetScale manages has to be created by hand in its
  dashboard.
- Reverse it if: Doppler gains per-secret access control on service tokens,
  or production's database gets a read replica with its own read-only URL.
