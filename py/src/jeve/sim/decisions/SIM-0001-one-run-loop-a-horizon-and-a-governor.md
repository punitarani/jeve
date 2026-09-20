---
id: SIM-0001
title: One run loop, a horizon, a single-writer lock, and a governor that pauses
status: accepted
date: 2026-09-20
deciders: ["claude"]
scope: ["py/src/jeve/sim/**", "py/scripts/run_fixture.py"]
tags: ["daemon", "pacing", "budget", "restart-safety", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["CORE-0002", "CORE-0003", "CORE-0004", "CORE-0007", "WORLD-0002", "LLM-0004"]
confirmation: "cd py && uv run pytest tests/test_daemon.py"
---

# SIM-0001 — One run loop, a horizon, a single-writer lock, and a governor that pauses

## Context and Problem Statement

The world has to run for ever, survive being killed, and also be replayable to
the byte from a cassette. Those pull against each other: a process paced by the
wall clock ends wherever the wall clock happened to be, and a replay has no
recording for whatever it would do next.

## Considered Options

- **A separate daemon beside the fixture script.** Two loops; "it passed in the
  fixture" then says nothing about the daemon. Loses.
- **Stretch the clock as the budget drains** (CORE-0002 as first written).
  Smooth, and needs a control loop with tuning nobody has time to validate
  tonight. Loses to the blunt version.
- **Let nights take real time**, for a faithful one day per 24 minutes. The town
  is then empty for 14 minutes in every 24 and a page showing it looks dead more
  often than not. Loses.
- **One loop, `--until`, an advisory lock, and a governor that stops the clock.** Taken.

## Decision Outcome

`python -m jeve.sim` is the only run loop; the fixture is that loop with pacing
off and a horizon. `--until` makes a wall-clock process replayable, a Postgres
advisory lock makes it the only writer, and the budget governor pauses the clock
until the window rolls over rather than changing how anything behaves.

Default pace is a fifteen-minute tick every fifteen real seconds, which is one
sim-day per 24 real minutes *of open hours*. Closed hours pass ten times faster.
That departs from the brief's "one sim-day per 24 real minutes": a full day
takes about eleven real minutes. `JEVE_SIM_DAY_MINUTES` changes the tick rate.

The governor implements CORE-0002 as stop-and-wait. A sim-day's worth of real
time has `JEVE_DAILY_BUDGET_USD` (default $2.00) of live model spend; spend it
and the status becomes `paused_budget` until the window ends. Sim time
stretches; no rule changes. The $12/$16/$20 ladder is separate and final: on
refusal the process exits 4 with status `halted`.

The lock is taken with a ten-second wait, because after `kill -9` the dead
backend holds it until Postgres notices the socket has gone, and a supervisor's
immediate restart would otherwise lose to its own corpse. `seed()` takes the
same lock, so a test run against a live daemon's database fails loudly instead
of truncating underneath it.

Restart is not a procedure. It is running the same command again.

### Consequences

- Good: a killed daemon and a finished fixture are recovered identically.
- Good: replay and live stop at the same sim time whatever the wall clock did.
- Bad: not the pacing that was asked for. Nights are compressed.
- Bad: stop-and-wait is visible — the town freezes when the budget is spent. At
  measured costs ($0.007 per sim-day) the default budget is ~300x headroom, so
  this is a fuse, not a throttle.
- Bad: one writer means one process. Sharding the world is out of scope.
- Reverse it if: spend approaches the daily budget in normal running, at which
  point a freeze is the wrong failure and stretching is worth its tuning.
