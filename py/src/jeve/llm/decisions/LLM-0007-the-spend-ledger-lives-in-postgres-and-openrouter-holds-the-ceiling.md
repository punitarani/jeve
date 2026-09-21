---

id: LLM-0007
title: the spend ledger lives in Postgres and OpenRouter holds the ceiling
status: accepted
date: 2026-09-21
deciders: ["devin"]
scope: ["py/src/jeve/llm/ledger.py", "py/src/jeve/llm/budget.py", "py/src/jeve/llm/gateway.py", "py/migrations/0008_spend_ledger.sql", "py/tests/test_ledger_and_budget.py"]
tags: ["cost", "safety", "deployment", "agent-decided"]
supersedes: ["LLM-0004"]
superseded-by: null
relates-to: ["CORE-0002", "LLM-0001", "OPS-0001"]
confirmation: "cd py && uv run pytest tests/test_ledger_and_budget.py"

---

# LLM-0007 — the spend ledger lives in Postgres and OpenRouter holds the ceiling

## Context and Problem Statement

LLM-0004's locked JSONL ledger assumed one checkout and one disk. Deployed,
both assumptions break: a Fly machine's disk is ephemeral, and the daemon and
the API are different machines, so a file gives two meters neither process can
see and a restart loses. Meanwhile the ceiling that actually binds moved —
OpenRouter enforces the account cap server-side, so the local ladder's job
shrank from kill switch to observability both processes must agree on.

## Considered Options

- **Keep the file, put it on a volume.** Rejected: volumes attach to one
  machine; the daemon and API still could not share a meter.
- **Per-process files.** Rejected: two meters, both lost on restart, and the
  run-cap already lives in memory — a second file adds nothing.
- **An append-only Postgres table with the same semantics.** Taken: every
  process already holds a connection, and one table is the only store both
  sides share.

## Decision Outcome

`spend_ledger` is an append-only table; `SpendLedger` keeps its
reserve/settle/release/baseline/remote API with `read()` as SQL aggregation,
and `authorise` holds a transaction-level advisory lock across read+reserve.
Ceilings are env-tunable and set high; OpenRouter's 402 — surfaced as
`ProviderBudgetError` — is the real stop, and the daemon answers it with
`waiting_on_budget`, not a halt (SIM-0003).

### Consequences

- Good: the meter survives restarts and is shared by every process; `ops/`
  shrinks to diagnostics.
- Bad: a spend check needs the database — `make smoke` gains a `db-up`
  prerequisite and the ledger tests skip without Postgres.
- Reverse it if: ledger writes ever show up in tick latency; they are
  milliseconds, so that would mean something else broke first.
