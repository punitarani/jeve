---
id: WORLD-0002
title: A tick owns its transaction, and puts its sequences back
status: accepted
date: 2026-09-20
deciders: ["claude"]
scope: ["py/src/jeve/world/engine.py", "py/src/jeve/db.py", "py/tests/test_resume.py", "py/tests/test_daemon.py"]
tags: ["postgres", "restart-safety", "determinism", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["CORE-0007", "CORE-0005", "API-0001", "SIM-0001"]
confirmation: "cd py && uv run pytest tests/test_resume.py tests/test_daemon.py"
---

# WORLD-0002 — A tick owns its transaction, and puts its sequences back

## Context and Problem Statement

CORE-0007 says one transaction per tick, so that `kill -9` at any instant loses
at most the tick in flight. Session 1 argued this from the design and did not
test it. Writing the test — a child process that SIGKILLs itself inside `_emit`,
restarted and byte-compared against an uninterrupted run — found two ways the
claim was false.

First, on a psycopg connection that is not in autocommit mode, *any* earlier
statement has already opened a transaction implicitly, and `conn.transaction()`
inside that is a savepoint. The run loop reads `sim_meta` before each tick, so
every tick was a savepoint in one long transaction that was committed only when
the night skip happened to call `commit()`. One transaction per sim-day. A kill
lost the day; a second session saw nothing until nightfall. No test caught it
because a writer always sees its own uncommitted rows.

Second, Postgres sequences do not roll back. A tick that dies after drawing ids
undoes its rows but not the ids, so the re-run numbers its events differently —
and `events.seq` is content: it appears inside `causes` and payloads.

## Considered Options

- **Require autocommit connections.** Fixes the first problem for callers who
  remember. The engine cannot enforce it, and the failure is silent. Loses.
- **Gapless ids from a counter table instead of sequences.** Correct, but puts a
  row lock on the hot path of every insert for a problem that only exists after
  a crash. Loses.
- **Exclude `seq` and ids from the comparison.** Makes the test pass by not
  testing the thing that broke. Loses.
- **The tick commits whatever is open, then runs everything — including the read
  of the clock — in one real transaction; and with a single writer, sequences are
  set back to max+1 at startup and after any failed tick.** Taken.

## Decision Outcome

`Engine.tick()` ends any open transaction and then does all of its reads and
writes inside one real `BEGIN...COMMIT`, so a tick is durable and visible to
other sessions the moment it returns. Every serial column's sequence is reset
to `max+1` when an engine starts and after any tick that raises.

The columns are enumerated from the catalogue (`pg_depend`), so a table added
later is covered without anyone listing it. This is safe only because there is
exactly one writer, which SIM-0001's advisory lock guarantees.

It also makes API-0001's promise to clients — `seq` is dense, a cursor cannot
skip an event — true after a crash rather than only on a good day.

### Consequences

- Good: `tests/test_resume.py` kills a Jev-replay run three times mid-transaction
  and gets thirteen tables byte-identical, ids and `causes` included.
- Good: the API can serve a world while it is running. It could not before.
- Bad: a commit per tick instead of per day. Measured cost is invisible at a
  tick every fifteen seconds; the flat-out fixture went from ~5s to ~6s.
- Bad: resyncing sequences is wrong the moment there are two writers. The lock
  is what stands between this and silent id reuse.
- Reverse it if: the world is ever sharded across writers. Then ids must come
  from somewhere that does not assume it is alone.
