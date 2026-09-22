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

The causal timeline opened on one fetch of the newest 600 events, oldest first,
in a 60vh scroll box. The clock runs far faster than real time, so nobody
watches an event happen — they arrive to history, and the thing they came for
was at the bottom of six hundred rows. Six hundred was also the whole world:
nothing before that window was reachable, ever.

Reversing the list is the easy half. `/events` could only walk forwards —
`WHERE seq > after` was unconditional (API-0001) — so "the page before this
one" was not a question the API could be asked, and it is exactly the question
a reader scrolling into the past asks, repeatedly.

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

`more` comes from selecting `limit + 1` rows and trimming — the probe row is
always the one beyond the window in the direction of travel — so the client
never learns it has reached the start of the log by asking for a page that is
not there.

This extends API-0001 rather than replacing it: the seq is still the only
cursor a client tracks, and still the one concept behind pagination, streaming
and reconnection. It just has a direction now.

### Consequences

- Good: one integer still pages, now either way, with no gap and no duplicate
  in either direction.
- Good: history before the opening window is reachable at all, in 200-row
  steps, and costs nothing until a reader scrolls for it.
- Neutral: the opening window stays at 600. Shrinking it to a scroll page's 200
  was tried and reverted — `encounter` is most of the log and is hidden by
  default, so 200 raw events is about 50 rows, and the newest outage can sit
  900 events back. The e2e suite caught a first paint with no incident on it.
- Good: older rows append below the fold, so loading more never moves what the
  reader is looking at — the same instinct as refreshing only the header.
- Bad: kind and org filtering stays client-side, so a page can arrive leaving
  nothing new on screen and the lane pulls again until it fills — sequential
  requests on a narrow filter. Moving the filters to the server would break the
  chip counts (deliberately counted over everything loaded) and the cascade
  that pulls a filtered-out kind back on screen.
- Bad: that loop has to be told when to give up. An empty lane keeps the
  sentinel on screen for ever, so `hide all kinds` would walk the whole log to
  show nothing; it stops when nothing is visible at all, since no page can put
  a row on screen. An e2e test counts the requests.
- Bad: the DOM grows unbounded as a reader scrolls back. The foreground log is
  a few thousand events, so the ceiling is reachable and harmless.
- Reverse it if: the log outgrows what a browser will hold. The lane then needs
  windowing, and this envelope is what a windowed list would page on anyway.
