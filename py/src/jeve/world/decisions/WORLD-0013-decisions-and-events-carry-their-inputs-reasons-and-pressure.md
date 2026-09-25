---
id: "WORLD-0013"
title: "Decisions and events carry their inputs, reasons and pressure"
status: "accepted"
date: 2026-09-24
deciders: ["claude"]
scope: ["py/migrations/0015_signal.sql", "py/src/jeve/world/engine.py", "py/src/jeve/world/space.py", "py/src/jeve/decide/questions.py", "py/src/jeve/evals/metrics.py", "py/tests/test_field_report.py"]
tags: ["signal", "decisions", "events", "payments", "typed-decisions", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["WORLD-0005", "WORLD-0011", "MEM-0004", "WORLD-0014", "EVAL-0001"]
confirmation: "cd py && uv run pytest tests/test_field_report.py tests/test_questions.py"
---

# WORLD-0013 — Decisions and events carry their inputs, reasons and pressure

## Context and Problem Statement

A decision row kept the distribution and the answer, not what it was asked
on. By the time anyone looked, the facts had moved (a runway, a backlog, who
was in the room), so a decision could not be explained from its own row.
Events said that something happened and seldom why. A bill paid late said
nothing about why it was late, whether anyone had asked for it, or whether the
payer had promised to pay. The field report could count lateness but not
explain it. The eval harness could say a world was plausible, not why.

## Considered Options

- **Keep the inputs on the row, typed; ask for the reason the world keeps;
  record the pressure that was applied.** Taken.
- **Reconstruct inputs from world state when asked.** Loses: the state is
  mutable, and the facts at the moment of decision are gone.
- **A generated rationale per decision.** Loses: nothing generated may be read
  back (GEN-0001), and prose cannot be counted.

## Decision Outcome

Every decision stores the facts it was asked on (`decisions.facts`). A late
bill carries a typed reason, and the pressure put on it is recorded: how often
it was chased, whether it was raised in person, and any promise to pay.
Events name what their consumers need to explain them.

- `payment.timing` also asks *why not today*, from a closed list: not due
  yet, cash flow, the payment routine, a sign-off, a query, forgotten, other
  bills first. The last reason given is kept on the bill (`late_reason`). The
  list comes from the trade surveys' reasons (Atradius US 2025: liquidity,
  payment-process delays, disputes). The first list lacked "not due" and
  "routine", and Jev put 0.60 on "other": 17 of 24 real states from a 60-day
  world reached for it. With both added, and the question asked as a
  supposition, that fell to 0.02 and none reached for it.
- Chasing repeats weekly and counts (`chases`). Money talked over between two
  firms with a bill due marks it reminded in person (`reminded_sim`). A
  payer's next decision is told all three, and whether they promised.
- Payment, chase, encounter, cancellation and resignation events carry the
  amount, the lateness, the pressure, the tie between the two people and the
  reason, whichever apply.

### Consequences

- Good: on three 60-day Jev worlds, decisions keep 8.0 facts each (none
  before). Event payloads rose from 4.5 fields to 5.3. 96% of late bills carry
  a reason, 8% were raised in person, and a late bill was chased 0.43 times.
  The harness's `signal` table measures all of this (`ops/evals.md`).
- Good: late payment became something a model decides with reasons, and the
  harness can band the reason mix against its source (`late_reason_cash_flow`,
  0.20–0.50).
- Bad: one more question per bill and a jsonb column on the largest table.
  Adding "why not" changed `payment.timing`'s bytes, and with them its cache
  keys.
- Reverse if: `decisions.facts` costs more storage than the explanations it
  buys, measured on production. Then keep facts for model-made decisions only.
