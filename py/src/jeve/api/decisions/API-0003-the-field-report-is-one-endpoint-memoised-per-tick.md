---
id: "API-0003"
title: "The field report is one endpoint, memoised per tick"
status: "accepted"
date: 2026-09-23
deciders: ["claude"]
scope: ["py/src/jeve/api/report.py", "py/src/jeve/api/app.py", "py/tests/test_api.py"]
tags: ["api", "reports", "caching", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["API-0001", "CORE-0011", "WEB-0007"]
confirmation: "cd py && uv run pytest tests/test_api.py"
---
# API-0003 — The field report is one endpoint, memoised per tick

## Context and Problem Statement

The first field report was a morning of read-only queries against production,
frozen into a page. `/reports` shows the same aggregates live: cash by firm
by day, the cache's hit rate by day, where staff spend their hours, what the
model was shown and what it answered. Every one of them is a scan over tables
that only grow (`decisions`, `ledger_entries`, `events`), and the page is
public. Without a decision, the obvious shapes are either a dozen endpoints the
browser fans out to, or one endpoint that rescans production for every open
tab.

## Considered Options

- **One `GET /report`, memoised on `(database, run_id, tick_seq, max seq)`** —
  taken.
- **One endpoint per chart** — rejected: a dozen round trips for one page, and
  a dozen places to keep in step with the contract, for data that is only ever
  drawn together.
- **A time-to-live cache** — rejected: a TTL is either stale inside a tick or
  recomputes when nothing has changed. The tick is exactly when the answer can
  change.
- **Materialised views refreshed by the daemon** — rejected: puts reporting
  work on the writer's transaction (WORLD-0002), for a page most ticks nobody
  is reading.

## Decision Outcome

`GET /report` returns every aggregate the report draws, in one `FieldReport`,
and computes it at most once per tick per process.

The memo key is the identity of the world's state: which database, which run,
which tick, which last event. Anything that could change an aggregate moves
one of them, so the memo is never stale, and a crowd of readers costs one
computation per tick. A lock makes concurrent readers wait for that one rather
than each starting its own, and they wait holding the lock, not a pooled
connection — eight waiting readers would otherwise be the whole pool. Clock
and health are read fresh on every request: a heartbeat's age is the one
number a reader must never be shown stale.

The aggregates read typed rows. One section (`mood_by_mind`) reads the
decision *request*, because the question it answers is what the model was
shown; `agent.moved` rather than the request supplies where staff spent their
time, so that section also works in a rules-only world.

### Consequences

- Good: one fetch per page, one contract, bounded load however many tabs are
  open.
- Bad: the first reader after each tick pays the full computation (tens of
  milliseconds on a five-day fixture; it grows with the run). The answer
  tables are capped at the sixty most-used calls per question set.
- What would reverse it: the computation taking longer than a tick. Then the
  aggregates should be maintained incrementally, not recomputed.
