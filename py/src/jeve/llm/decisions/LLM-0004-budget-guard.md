---

id: LLM-0004
title: Guard spend with reservations in a locked ledger at the repo root
status: superseded
date: 2026-09-20
deciders: ["claude"]
scope: ["py/src/jeve/llm/budget.py", "py/src/jeve/llm/ledger.py"]
tags: ["cost", "safety", "agent-decided"]
supersedes: []
superseded-by: "LLM-0007"
relates-to: ["CORE-0002", "LLM-0001"]
confirmation: "cd py && uv run pytest tests/test_ledger_and_budget.py"
---

# LLM-0004 — Guard spend with reservations in a locked ledger at the repo root

## Context and Problem Statement

An agent spending real money unattended needs a ceiling enforced in code. The
obvious implementation — add up what responses cost, refuse past a threshold —
has three holes: a response's cost is only known *after* it is billed, so
concurrent calls all authorise against a stale total; an in-memory counter
resets on restart; and a crashed process loses whatever it spent.

## Considered Options

- **Count calls, not dollars** (workbench's `BudgetedLM`). Rejected: a call is
  not a unit of cost, and it resets per process.
- **Poll `/api/v1/key` and trust it.** Too coarse and too laggy to gate on.
- **Reserve worst case, settle at actual, in a locked file.** Taken.

## Decision Outcome

Every call reserves its worst-case cost in an append-only locked ledger before
it is issued and settles at the real cost afterwards; effective spend counts
settled costs plus every reservation that never settled.

Consequences of that rule, each deliberate. Sixteen concurrent calls cannot
each authorise against $0 of settled spend. A crashed process leaves its
reservation standing, so the ledger over-counts rather than under-counts —
the right direction for a ceiling. A response that omits `usage.cost` is priced
from the catalogue and flagged estimated, never booked as free, because free is
how a ceiling quietly stops working. The ledger lives at the repo root, found
by walking up to `.git`, so a script run from a subdirectory shares one meter.

Two judgement calls I made alone. The brief says stop at $20 in one place and
$25 in another, the latter unreachable if the module refuses at $20; I
implemented the stricter ladder — $12 refuses exploratory work, $16 refuses
everything and triggers the handoff, $20 is the backstop. And the brief says to
trust the remote figure on divergence, which taken literally lets a lagging
meter *refund* spend already made; the local total is therefore a floor.

### Consequences

- Good: the ceiling survives restarts, crashes and concurrency.
- Bad: reservations are conservative, so the ceiling binds slightly early.
- Bad: a torn ledger line from a killed process is skipped, so an interrupted
  call may be uncounted — bounded by one call.
- Reverse it if: reservation over-counting proves large enough to waste budget.
