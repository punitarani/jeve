---
id: SIM-0004
title: the daemon outlives its database, and the night is a dial
status: accepted
date: 2026-09-22
deciders: ["claude"]
scope: ["py/src/jeve/sim/daemon.py", "py/tests/test_daemon.py"]
tags: ["daemon", "robustness", "pacing", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["SIM-0002", "SIM-0003", "CORE-0002", "CORE-0003"]
confirmation: "cd py && uv run pytest tests/test_daemon.py"
---
# SIM-0004 — The daemon outlives its database, and the night is a dial

## Context and Problem Statement

Two holes in a world meant never to stop, found by reading three hours of a
live run's usage graph and asking what the gaps were.

Dead time was skipped at a fixed `NIGHT_SPEEDUP = 10`, so at the default pace a
weeknight is 78 real seconds of a world that is alive, paying nothing and
visibly doing nothing; a weekend is 3.7 real minutes. The only dial was
`JEVE_SIM_DAY_MINUTES`, which shortens the night by speeding up the *day* —
and the day is where every model call is. Paying twice as much to halve the
silence was the only trade on offer.

The second hole is fatal rather than cosmetic. `run()` opened one connection
and kept it for the life of the process, so a failover, a restart, a pooler
dropping the session or a laptop changing network raised
`psycopg.OperationalError` out of the daemon. A container restarts; `make sim`
on the machine this actually runs on does not, and `sim_meta` is left reading
`running`.

A third thing fell out of that reading: `sim_meta.speed` has been `NOT NULL
DEFAULT 1.0` since the first migration, is served by `/state` and is in the
generated contract — and nothing has ever written it.

## Considered Options

- **Keep the constant; tell people to lower `JEVE_SIM_DAY_MINUTES`.** Rejected:
  it prices a cosmetic fix in model calls.
- **Give the world overnight work so there is no dead time.** The right answer
  to the realism question, and the reversal CORE-0003 names — but it is a world
  change, so it re-records the cassette. Not this record.
- **Let a lost connection end the process; rely on a supervisor.** Rejected:
  the deployment with a supervisor is not the one this mostly runs in.
- **`JEVE_NIGHT_SPEEDUP`, and a lost connection is weather.** Taken.

## Decision Outcome

Dead-time speedup is `JEVE_NIGHT_SPEEDUP` / `--night-speedup`, and losing the
database is weather in the sense of SIM-0002: the daemon takes another
connection and runs the same tick again, for ever, rather than exiting.

Reconnection is nearly free because the recovery already existed and was only
ever used one way. A tick is one transaction (CORE-0007), so a tick whose
connection died changed nothing; `Engine.__init__` resyncs every sequence
because "whatever ran before us may have died mid-tick" (WORLD-0002); the
recorder reopens its own closed connection already. Building a new `Engine` on
a new connection *is* the recovery — `_supervise` only decides to do it, and
the policy, the cache's statistics and the run totals now outlive the session
they were reading from.

Two asymmetries are deliberate. `--seed-world` is honoured on the first
connection only: answering a dropped connection by deleting the world it
interrupted is the one unrecoverable thing here. And while the database is gone
there is no status to write and no heartbeat to beat, so a stderr line is the
only record — the opposite of SIM-0002 and SIM-0003, where saying so in
`sim_meta` is most of the point.

`sim_meta.speed` now carries sim-seconds per real second, and nought whenever
the world is paused, halted or waiting: a stopped world is not a slow one.

### Consequences

- Good: a night at `JEVE_NIGHT_SPEEDUP=60` is 13 real seconds — shorter than
  one tick's own pacing sleep, and it costs nothing to remove.
- Good: a Postgres restart no longer ends the run, on a laptop or anywhere.
- Bad: an outage is invisible to anything reading `sim_meta`, because that is
  the thing that is gone. A stale `heartbeat_at` is the only signal, which is
  what `/state`'s `stalled` flag already watches.
- Bad: one more environment variable, against the house rule. It earns it by
  being the only way to buy silence back without buying model calls.
- What would reverse it: the night becoming load-bearing, at which point there
  is no dead time to skip and the dial turns nothing.
