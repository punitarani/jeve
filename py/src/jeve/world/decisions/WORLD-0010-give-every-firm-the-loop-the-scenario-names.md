---
id: "WORLD-0010"
title: "Give every firm the loop the scenario names"
status: "accepted"
date: 2026-09-24
deciders: ["claude"]
scope: ["py/src/jeve/world/engineering.py", "py/src/jeve/world/customers.py", "py/src/jeve/world/timesheets.py", "py/src/jeve/world/shocks.py", "py/migrations/0011_loops.sql", "py/tests/test_loops.py"]
tags: ["flows", "decisions", "scenario", "calibration", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["WORLD-0004", "WORLD-0009", "WORLD-0011", "MEM-0003", "DECIDE-0001", "CORE-0009"]
confirmation: "cd py && uv run pytest tests/test_loops.py tests/test_questions.py"
---

# WORLD-0010 — Give every firm the loop the scenario names

## Context and Problem Statement

The scenario (docs/plan/scenario.md §3, §5) gives each firm an internal loop and
names seven behaviours a viewer should see. The field report's world had few
of them: debt was a constant, no customer could leave, nobody worked around an
outage, nobody disputed a bill or declined an order, the law firm's bills were
random numbers untouched by its own time tracking, and the only shock was an
outage. Conversation moved nothing (3,370 of 3,371 knowledge rows first-hand).

## Considered Options

- **More rules.** Cheap, and a rule cannot differ by persona, which is what #5
  exists to test. Loses.
- **Each loop a decision at the event that prompts it, with a rules twin, the
  amounts and consequences in code.** WORLD-0004's shape. Taken.

## Decision Outcome

Each firm's loop is a decision at the moment it arises, with a rules twin and
its consequences in code: engineering allocation and deploys (debt is live and
drives the hazard), trust revised after an outage and renewal asked of
customers at risk, a workaround chosen with every report, disputes and their
resolution, time logged or not at the law firm, the cafe's cover, stock and
catering acceptance, and the close's wait/nag/estimate. Shocks (Poisson 1.5 a
week, keyed by the week) are the environment they answer to.

Asked at the event, never on a timer (DECIDE-0001's hazard rule): renewal only
of customers at risk, the workaround with the report, disputes once per bill.
Every new `choice` carries `other`. The law firm bills logged hours shared by
the drawn size of each matter, so its amounts are behaviour now and the soak's
counterfactual compares the drawn work (`work_cents`), not the invoice.

Calibrated on the rules twin (`make calibrate`): the base hazard is 0.006 an hour,
not 0.016; at the seeded debt the old rate was an outage a day, harmless while
outages changed nothing lasting and a certain churn spiral once customers
remember them.

### Consequences

- Good: behaviours #4 (firefighting trap), #5 (workaround divergence) and #7
  (churn bargaining) can now occur; runaway politeness and a conflict-free
  economy are measurable failures rather than the only possibility.
- Bad: many more question sets; each wording is a cassette entry, and the
  golden cassette must be re-recorded.
- Bad: the rules twin's trust and renewal odds are tuned, not measured.
- Reverse it if: a loop's decision shows no persona or situation dependence
  under Jev in the situation probe — then it is a rule wearing a question.
