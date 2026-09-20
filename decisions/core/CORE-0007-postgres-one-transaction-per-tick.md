---
id: CORE-0007
title: Persist to Postgres with one transaction per tick and a causal event log
status: accepted
date: 2026-09-20
deciders: ["punitarani"]
scope: []
tags: ["persistence", "durability", "postgres"]
supersedes: []
superseded-by: null
relates-to: ["CORE-0005"]
confirmation: null
---

# CORE-0007 — Persist to Postgres with one transaction per tick and a causal event log

## Context and Problem Statement

The world must survive `kill -9` at any instant and resume as if uninterrupted,
while a second process serves a dashboard reading the same data. It must also
be able to answer "what caused this?" — that question is the product.

## Considered Options

- **SQLite**, as workbench uses. Rejected: two processes, notifications,
  partitioning, and the stated constraint all point elsewhere.
- **Pure event sourcing**, state as a fold over the log. Rejected: workbench's
  roll-forward resume reads the whole log into memory, which is fine for 130
  days and unbounded for forever.
- **Postgres: append-only log *and* materialised state, committed together.** Taken.

## Decision Outcome

Every tick commits its domain mutations, events, decisions, scheduler changes
and clock advance in a single transaction; events are append-only and carry a
`causes` array of the event ids that led to them.

`causes` is the most important column in the schema: a cascade becomes a
recursive query rather than an inference, which is what lets the UI show
"outage → tickets → late invoices → cash trough" instead of asking a viewer to
notice it. Domain tables are relational with real constraints, because the
hard invariants — double-entry balance, referential integrity, no negative
inventory — are cheapest and most trustworthy as foreign keys and triggers.

Model responses are written as they arrive, outside the tick transaction, so a
re-executed tick finds them by hash and is never billed twice. The simulation
holds a session-level advisory lock, so a second writer cannot start.

**No Redis.** Everything it would do is already durable here: `LISTEN/NOTIFY`
for viewers, a `jobs` table with `SKIP LOCKED` for async work (which *must*
survive a kill), the model-call table as cache, and an in-process token bucket.
It is not load-bearing, so it is not included.

### Consequences

- Good: crash recovery is one rule — re-run the tick named by `sim_meta`.
- Bad: tick latency now includes a commit.
- Reverse it if: more than one API replica or hundreds of viewers need a broker.

Long form, with the schema and read patterns: `docs/design/009-persistence.md`.
