---
id: API-0001
title: Make the event seq the only cursor the client tracks
status: accepted
date: 2026-09-20
deciders: ["claude"]
scope: ["py/src/jeve/api/app.py", "apps/web/src/lib/api.ts"]
tags: ["api", "streaming", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["CORE-0007", "WEB-0001"]
confirmation: "cd py && uv run pytest tests/test_api.py"
---

# API-0001 — Make the event seq the only cursor the client tracks

## Context and Problem Statement

The dashboard needs a first paint and then a live feed, over a connection that
will drop — a closed laptop, a proxy, a restarted API. Reconnecting must not
lose events or replay them, and the sim runs far faster than real time so a gap
is easy to create and hard to notice.

## Considered Options

- **Timestamps as the cursor.** Rejected: several events share a sim-second, so
  a resume either drops or duplicates whatever sits on the boundary.
- **A server-held subscription with its own state.** Rejected: state on both
  ends that can disagree, for one reader.
- **The monotonic `seq` as the only cursor.** Taken.

## Decision Outcome

Every endpoint that returns events also returns the `seq` it is current as of,
and `/stream` takes `after=<seq>`, so a reconnect is exactly "give me what
comes after this" with no gap and no duplicate.

The stream closes itself after a bounded lifetime rather than living forever.
Long-lived SSE connections get killed by proxies and sleeping laptops anyway; a
server that recycles on its own terms is easier to reason about than one
waiting to be cut off, and resuming is free because the cursor already exists.
It also makes the endpoint testable without a hanging read — the first version
of that test wedged the suite for ten minutes.

### Consequences

- Good: one concept covers pagination, streaming, and reconnection.
- Good: a client that stores one integer can always catch up exactly.
- Bad: polling the database on an interval rather than `LISTEN/NOTIFY`, which
  is fine for one reader and a tick every few seconds, and would not be for
  many. Revisit when there is more than one viewer.
- Reverse it if: the poll shows up in database load, or viewers need
  sub-second latency.
