---
id: "WORLD-0009"
title: "Give the economy sinks and consequences"
status: "accepted"
date: 2026-09-24
deciders: ["claude"]
scope: ["py/src/jeve/world/economy.py", "py/src/jeve/world/flows.py", "py/src/jeve/world/seed_world.py", "py/src/jeve/sim/soak.py", "py/tests/test_consequences.py"]
tags: ["economy", "insolvency", "households", "calibration", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["WORLD-0005", "WORLD-0008", "DECIDE-0001", "CORE-0009", "WORLD-0007"]
confirmation: "cd py && uv run pytest tests/test_consequences.py tests/test_soak.py"
---

# WORLD-0009 — Give the economy sinks and consequences

## Context and Problem Statement

The golden-20260920 field report found an economy with nothing at stake.
Tallybird paid $14.6k a week in wages against about $5.7k a month of revenue,
held its payroll 28 weeks in 33, and warned of insolvency every week to no one;
its founder ordered $420 of catering. Households took in $759k and spent $10.6k.
Three firms only accumulated: nobody paid rent, a supplier or tax. WORLD-0005
closed the loops that move money; it left out what happens when the money is
not there.

## Considered Options

- **Recalibrate prices and stop there.** Every firm survives because it was
  tuned to; a firm in trouble still has no one to notice. Loses.
- **Consequences as rules only.** Quitting, borrowing and raising prices are
  judgements with persona in them; as rules they are a screensaver. Loses.
- **Sinks as rules, consequences as decisions at the events that should
  prompt them, failure as a rule.** Taken.

## Decision Outcome

Rent, stock, quarterly tax on profit and household spending are rules; staff
two paydays unpaid decide whether to leave (`leave.consider`), a firm's head
reviews its position monthly and on every warning (`founder.review`: raise
prices, cut costs, chase debts, borrow, carry on), vacancies are refilled by
decision (`hire.decision`), and a firm four paydays behind has failed.

Households are one purse per employer. Outside subscribers pay per seat (3 to
20 at $49, a fact about each subscriber), which puts Tallybird about five months
from the edge on its seeded cash, as the scenario asks. What a firm decided is
`orgs.policy`, the column nothing wrote. A world seeded before this is brought up
to date when its engine starts (WORLD-0007's reason: production migrates while
the old daemon writes), and paydays it missed before then are not counted.

### Consequences

- Good: every consequence the report found missing exists, is caused by the
  event that should prompt it, and is asked once per event, not on a timer
  (DECIDE-0001's hazard rule; "rare-event inflation" is the failure it avoids).
- Good: money now reaches people: an unpaid firm's staff stop buying coffee
  because their own purse empties, not the town's.
- Bad: failure is absorbing. A long-running world can lose a firm for good;
  Tallybird failing moves its customers to another vendor and ends outages.
- Bad: the production world's firms start under the new rules at once, and a
  Tallybird already months behind has four paydays to recover in.
- Reverse it if: firms fail in most seeded runs on rules (the calibration is
  wrong) or never come near the edge under Jev (the consequences are inert).
