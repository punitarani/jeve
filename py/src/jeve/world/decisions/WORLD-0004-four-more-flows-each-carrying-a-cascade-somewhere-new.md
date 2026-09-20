---
id: WORLD-0004
title: Four more flows, each built to carry a cascade somewhere new
status: accepted
date: 2026-09-20
deciders: ["claude"]
scope: ["py/src/jeve/world/flows.py", "py/tests/test_flows.py", "py/src/jeve/core/clock.py"]
tags: ["flows", "ledger", "causality", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["WORLD-0001", "WORLD-0003", "DECIDE-0003", "CORE-0003", "CORE-0007"]
confirmation: "cd py && uv run pytest tests/test_flows.py"
---

# WORLD-0004 — Four more flows, each built to carry a cascade somewhere new

## Context and Problem Statement

Four flows were left from the scenario: payroll, the monthly close, catering and
service credits. A flow done improperly — an event kind that fires and changes
nothing — is worse than a flow not done, because it pads the event log and
proves nothing. So each had to earn its place by the same test: does it carry a
cascade somewhere it could not reach before, and can a query show it?

## Considered Options

- **Thin versions**: a decision, an event, a ledger entry, no consequence.
  Quick, and indistinguishable from noise in the causal graph. Loses.
- **Let the model set amounts** (the size of a credit, a wage, a lunch bill).
  Contradicts WORLD-0001: the referee is code and money is never moved by a
  model. Loses.
- **Each flow a judgement between two code-enforced facts, with a consequence a
  test can walk.** Taken.

## Decision Outcome

Four flows, behind the same `Policy` seam as the first six, each with a Jev
question set, a rules twin, and tests that fail without it. In every one the
model decides a judgement; amounts, eligibility and whether the cash exists are
rules.

**Credits.** When an outage ends, Tallybird's account manager decides per
subscribing firm what it is owed: nothing, a quarter of the month's fee, or the
month. Applied against an invoice the firm still owes and booked as the reverse
of the entry that created it; with nothing owed, nothing is credited, so a
receivable cannot go negative. This takes the chain that begins with two people
meeting in the cafe all the way to the ledger: encounter, escalation, outage
ends, credit issued.

**Payroll.** Fridays at ten, Ledgerline's payroll clerk releases each firm's
wages unless the hours behind them cannot be seen. Firms that keep their time in
TimeTrack cannot be paid while it is down; the others can. An outage in one
firm's product becomes a late payday in another's, and the late `payroll.paid`
cites both the hold and the end of the outage. A hold is said once, not every
tick; a firm without the cash is looked at again tomorrow, not in fifteen minutes.

**The monthly close.** The working day after month-end, a Ledgerline accountant
scores each client's books for readiness. A client whose month-end invoices are
stuck behind an outage has no revenue figure to close on, so the close — and
Ledgerline's own fee, invoiced on completion — is deferred. This is the second
thing space changes: with encounters, someone presses the vendor and Halloran
closes on Friday morning; without, it is put off. "Stuck" is read from the event
log, not the scheduler's queue, because the scheduler has already dequeued the
tick's due rows before any is handled — found by the control-arm test.

**Catering.** Twice a week a firm's office manager may order lunch in. It is
delivered the next day at noon and billed by the cafe — and carried across the
plaza by whoever at the cafe is free, which puts a cafe employee inside another
firm's office. One person cannot carry two lunches in the same tick.

Building the close exposed a session-1 bug: dead time was skipped to the next
*office* opening, which silently dropped the cafe's 07:00-09:00 trade on every
day after the first, and all of Saturday. `next_open` fixes it.

### Consequences

- Good: the longest causal chain in the world ends in money, and a test walks it.
- Good: two independent control-arm tests now show space changing outcomes.
- Bad: wages leave the world as `expense` and never return as cafe spending.
  Staff are not yet customers of each other's firms.
- Bad: the credit policy lives in the wording of three option descriptions.
  Rewording them changes what Tallybird owes.
- Bad: catering demand is a propensity with no feedback: nobody orders less
  because last week's lunch was late.
- Reverse it if: a household sector is added (wages become transfers to people),
  or credits need to be negotiated between two agents rather than decided by one.
