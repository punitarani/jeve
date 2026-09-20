---
id: CORE-0003
title: Run on a simulated clock advanced by a discrete-event scheduler
status: accepted
date: 2026-09-20
deciders: ["punitarani"]
scope: []
tags: ["clock", "scheduler", "world"]
supersedes: []
superseded-by: null
relates-to: ["CORE-0002", "CORE-0004"]
confirmation: null
---

# CORE-0003 — Run on a simulated clock advanced by a discrete-event scheduler

## Context and Problem Statement

Four offices need a shared notion of time. Wall-clock 1:1 means the offices are
shut whenever the viewer is awake, and checking whether a cascade appears
"within one sim-week" takes a real week per attempt. Smallville's ten-sim-second
step burns 8,640 steps a day to model people sitting at desks.

## Considered Options

- **Wall clock, 1:1.** Trivially cheap, fatally slow to iterate on.
- **Fixed speed multiplier.** Spend becomes uncontrolled (CORE-0002).
- **Simulated clock, discrete-event, budget-paced.** Taken.

## Decision Outcome

Sim time is an integer count of sim-seconds from a seeded epoch, advanced only
inside the tick transaction, with a 15-sim-minute scheduler quantum and pacing
set by the budget governor.

Nothing in the simulation core may read the wall clock; a lint rule enforces
it. Dead time is skipped visibly — a sim-night passes in about a real minute,
costing nothing because nothing calls a model, but a viewer still sees that a
night happened. A stopped process means a paused world: on restart the clock
resumes where it stopped, with no catch-up and no concept of missed time.

### Consequences

- Good: a viewer who checks in twice a day returns to sim-weeks of history, so
  calendar-driven behaviour is observed hundreds of times a month.
- Bad: memory compaction is mandatory from day one, not a later optimisation.
- Bad: the event log grows by tens of thousands of rows per real day.
- Reverse it if: dead-time skipping hides something worth seeing, e.g. if
  overnight on-call becomes a real mechanic.

Long form: `docs/design/001-time-model.md`.
