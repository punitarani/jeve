---
id: "API-0002"
title: "Page the seq cursor both ways, and read the timeline newest first"
status: "accepted"
date: 2026-09-21
deciders: ["claude"]
scope: ["py/src/jeve/api/app.py", "py/src/jeve/api/contracts.py", "apps/web/src/lib/api.ts", "apps/web/src/components/Dashboard.tsx"]
tags: ["api", "web", "pagination", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["API-0001", "WEB-0001"]
confirmation: "cd py && uv run pytest tests/test_api.py"
---

# API-0002 — Page the seq cursor both ways, and read the timeline newest first

## Context and Problem Statement

The causal timeline opened on a single fetch of the newest 600 events, oldest
first, inside a 60vh scroll box. Both halves of that were wrong for a reader.
The clock runs far faster than real time, so nobody watches an event happen —
they arrive to history, and the thing they came for was at the bottom of six
hundred rows. And six hundred was the whole world: there was no way to see
anything that happened before the window, ever.

Reversing the list is the easy half. The hard half is that `/events` could only
walk forwards — `WHERE seq > after` was unconditional (API-0001) — so "the page
before this one" was not a question the API could be asked. A reader scrolling
down into the past is asking exactly that question, repeatedly.

## Considered Options

- **A `before` cursor on `/events`, ascending rows, reversed in the client** —
  taken.
- **Return descending rows when paging backwards.** Rejected: the wire order
  would become a property of the query rather than of the endpoint, so
  `/stream`, `@jeve/world` and every test would have to know which way a page
  was taken to know what order it is in.
- **Grow `limit` and refetch the newest N.** Rejected: re-downloads everything
  already on screen, and the cost of reading further back rises with how far
  you have read.
- **Infer exhaustion from `len(events) == limit`.** Rejected: it spends a
  round trip at the end of history discovering there is none.

## Decision Outcome

`/events` takes `before=<seq>` as well as `after=<seq>`, and every page carries
a cursor at each end — `seq` (newest) and `oldest` — plus `more`, which says
whether another page exists in the direction this one travelled. Rows come back
ascending whichever way the window was taken; the timeline reverses once, where
it renders.

`more` is answered by selecting `limit + 1` rows and trimming, because the probe
row is always the one beyond the window in the direction of travel. That keeps
the client from learning it has reached the start of the log by asking for a
page that isn't there.

This extends API-0001 rather than replacing it: the seq is still the only cursor
a client tracks, and still the only concept behind pagination, streaming and
reconnection. It now just has a direction.

### Consequences

- Good: one integer still pages, now either way, with no gap and no duplicate
  in either direction.
- Good: history before the opening window is reachable at all, in 200-row
  steps, and costs nothing until a reader scrolls for it.
- Neutral: the opening window stays at 600. Shrinking it to a scroll page's 200
  was tried and reverted — `encounter` is most of the log and the dashboard
  hides it by default, so 200 raw events is about 50 rows, and in a ten-day
  fixture the newest outage sits some 900 events back. The e2e suite caught a
  first paint with no incident on it at all.
- Good: older rows append below the fold, so loading more never moves what the
  reader is looking at — the same instinct as refreshing only the header.
- Bad: kind and org filtering stays client-side, so a page can arrive and leave
  nothing new on screen. The lane keeps pulling until it fills or history runs
  out, which costs sequential requests on a narrow filter. Moving the filters
  server-side would break the chip counts (deliberately counted over everything
  loaded) and the cascade that pulls a filtered-out kind back on screen.
- Bad: the DOM grows without bound as a reader scrolls back. The foreground log
  is a few thousand events, so the ceiling is reachable and harmless.
- Reverse it if: the log grows past what a browser will hold, at which point the
  lane needs windowing and this envelope is what a windowed list would page on
  anyway.
