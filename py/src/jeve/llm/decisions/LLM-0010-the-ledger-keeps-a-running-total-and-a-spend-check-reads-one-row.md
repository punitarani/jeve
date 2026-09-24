---
id: "LLM-0010"
title: "the ledger keeps a running total, and a spend check reads one row"
status: "accepted"
date: 2026-09-24
deciders: ["claude"]
scope: ["py/src/jeve/llm/ledger.py", "py/src/jeve/llm/budget.py", "py/src/jeve/llm/gateway.py", "py/migrations/0011_spend_totals_and_read_indexes.sql", "py/tests/test_ledger_and_budget.py"]
tags: ["cost", "safety", "performance", "postgres", "agent-decided"]
supersedes: ["LLM-0007"]
superseded-by: null
relates-to: ["LLM-0004", "SIM-0003", "OPS-0001"]
confirmation: "cd py && uv run pytest tests/test_ledger_and_budget.py"
---
# LLM-0010 — the ledger keeps a running total, and a spend check reads one row

## Context and Problem Statement

LLM-0007 made `read()` a fold over the whole `spend_entries` table, and the
gateway reads four times per model call: the remote-check test, the check
under the lock, the reservation's own re-read, and the settle's. Three days
into the deployed run the table held 86k rows, each fold read 250k tuples in
about 50 ms, and on PlanetScale's PS-10 (an eighth of a vCPU) that one query
was 80% of all database time and 70% of the machine — CPU pinned at 100%
with the API's polling behind it. The cost grew with every call made, so
no size of instance was going to hold it for long.

## Considered Options

- **Read fewer times per call.** Drop the settle's read, cache the remote
  check in-process. Four folds become one; still O(rows) per call, still
  past the instance inside a month.
- **Index the fold.** A covering index makes the settle sum an index scan
  and does nothing for the anti-join that finds open reservations. Same
  growth, smaller constant.
- **Checkpoint rows inside the ledger.** Append-only stays pure, but a
  reservation opened before a checkpoint and closed after it needs the
  checkpoint to carry the open set. Correct and hard to explain.
- **A running total in its own row, moved by every append.** Taken. The
  ledger stays the append-only audit trail; the total is derived state the
  fold can rebuild.

## Decision Outcome

`spend_entries` stays append-only and every writer still takes the advisory
lock across read-modify-write (LLM-0007's rules stand); what a spend check
reads is the one row of `spend_totals`, which every append moves by exactly
what the fold would, and the fold survives as `rebuild()`: the migration's
seed, the repair, and what a ledger runs on open when the total is behind
the ledger's head.

The total's `as_of_seq` is the ledger's head when it was last moved. That is
what makes the deploy safe without coordination: migration 0011 seeds the row
from the fold while the old daemon is still appending without moving it; the
new daemon's first open sees the head has moved and folds the rest in. The
same path resets the test fixture's emptied table. The rest of LLM-0007 —
OpenRouter's 402 as the real stop, `waiting_on_budget` rather than a halt,
env-tunable ceilings set high — is unchanged and restated here only so this
record can stand alone.

The same migration adds two read indexes the investigation surfaced beside
the fold: `events (kind, tick_seq)` for the crowd count `GET /world/agents`
runs every five seconds per page (11% of database time as a bitmap scan of
every cafe event), and `amount_cents` carried in `ledger_entries_account` so
balance sums are index-only. Ordinary performance work, recorded here for
the incident, not as a decision.

### Consequences

- Good: a spend check is one row however long the run; the four reads per
  call the gateway makes are no longer worth restructuring around.
- Bad: two places must agree — the delta each kind applies and the fold —
  and a test holds them to it. A hand-run INSERT into `spend_entries` is not
  seen until a ledger next opens or `rebuild()` is called.
- Reverse it if: the total and the fold ever disagree in production after a
  ledger has opened, which would mean an append path that does not go
  through `_append`, and that is the bug to fix first.
