---
id: SIM-0002
title: The daemon outlives its model - wait, say so, retry the tick
status: accepted
date: 2026-09-20
deciders: ["claude"]
scope: ["py/src/jeve/sim/daemon.py", "py/src/jeve/sim/runner.py", "py/src/jeve/api/app.py", "py/migrations/**"]
tags: ["daemon", "robustness", "backpressure", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["CORE-0004", "SIM-0001", "WORLD-0002", "LLM-0006"]
confirmation: "cd py && uv run pytest tests/test_daemon.py"
---

# SIM-0002 — The daemon outlives its model: wait, say so, retry the tick

## Context and Problem Statement

CORE-0004 decided that a dead model means a paused world. It was never built
(audit `docs/audit/2026-09-21/README.md` A6.1, A11): the daemon caught exactly
two exceptions, budget exhaustion and a replay miss. Anything else the model
path could raise — a transport error after the gateway's own retries ran out, a
response of the wrong shape, the bridge's bare `TimeoutError` — killed the
process, while `sim_meta.status` went on saying `running` and the page went on
showing a live world. One HTTP 520 ended a 30-day soak.

A tick is one transaction (WORLD-0002), so a tick that raises has changed
nothing. Retrying it is safe by construction; nobody had written the retry.

## Considered Options

- **Let a supervisor restart the process.** Rejected as the only answer: a
  restart loop hammers a model that is down, and the page still lies in between.
- **Skip the failed decision and carry on.** Rejected by CORE-0004: that turns
  infrastructure weather into behaviour and writes it into the record.
- **Catch the model's failures, mark the world as waiting, retry the same tick
  with capped backoff.** Taken.

## Decision Outcome

The run loop treats `TransportError`, `ResponseShapeError` and `TimeoutError`
as weather. The tick is rolled back, `sim_meta.status` becomes
`waiting_on_model` with the error's class and first line in `last_error`, and
the same tick is tried again after a jittered backoff that doubles to a cap of
two minutes. The first tick that succeeds sets `running` and clears the error.
Budget exhaustion and a replay miss keep their own statuses and exits: they are
not weather, and retrying them cannot help.

The daemon writes a wall-clock heartbeat (`heartbeat_at`, and `lag_s`, how far
the last tick ran over its pacing) on every tick **and from its sleep loop**, so
a reader can tell a world that is asleep for the night from a process that has
died. The API reports what it reads and adds one judgement, `stale`, when the
heartbeat is older than a few sleep intervals.

"Is the world closed at this sim-time?" was answered in five places. It becomes
one function, because the next record to touch nights (on-call) would otherwise
have to change all five.

### Consequences

- Good: CORE-0004 is true of the running system, not just of the record.
- Good: the page can say `waiting on model` and mean it.
- Bad: a permanently broken model leaves a process retrying every two minutes
  for ever. That is what the status is for; it is cheaper than a dead world
  nobody noticed.
- Reverse it if: waiting exceeds 5% of wall time with a standby provider
  available — then fail over instead (CORE-0004's own condition).
