---
id: "MEM-0003"
title: "Trust is a typed belief, and a fact can be false"
status: "accepted"
date: 2026-09-24
deciders: ["claude"]
scope: ["py/src/jeve/memory/**", "py/src/jeve/world/customers.py", "py/migrations/0012_loops.sql"]
tags: ["memory", "beliefs", "diffusion", "rumour", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["MEM-0001", "MEM-0002", "WORLD-0011"]
confirmation: "cd py && uv run pytest tests/test_loops.py"
---

# MEM-0003 — Trust is a typed belief, and a fact can be false

## Context and Problem Statement

MEM-0001 promised typed belief slots revised by Jev `score` questions; none
existed. MEM-0002 made facts travel, but only two kinds (an outage, a planned
price rise), and the field report found talk moved nothing: 3,370 of 3,371
knowledge rows were first-hand. The scenario's diffusion behaviour (#6) needs
news that matters to someone who hears it, and its shock deck includes a rumour.

## Considered Options

- **A free-text memory of what someone thinks of the vendor.** Generated, and
  read back; GEN-0001 forbids it. Loses.
- **One typed slot, the first of MEM-0001's; more topics; truth as a column.**
  Taken.

## Decision Outcome

A subscriber's trust in the vendor is `persons.beliefs.vendor_reliability`, 0
to 4, revised by a J `score` after each outage they ran into and recovering a
level after a month without one; it gates renewal. Facts can now be about late
wages, a firm short of money, a vendor losing customers or a broken promise,
and `true_fact` is false for a rumour, which travels like any fact.

### Consequences

- Good: history matters. An outage last month shapes a renewal decision this
  month, and hearing that the vendor is in trouble puts a customer at risk even
  if no outage ever touched them — the scenario's #6 made causal.
- Good: a rumour and a fact are told apart in the data and nowhere else, so
  the effect of false news is measurable.
- Bad: one slot. Workload strain and price fairness, MEM-0001's other examples,
  are still to come.
- Reverse it if: trust never moves under Jev except where the rules twin's
  table would have moved it.
