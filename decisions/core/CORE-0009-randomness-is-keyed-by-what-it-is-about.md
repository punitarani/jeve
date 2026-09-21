---
id: CORE-0009
title: Randomness is keyed by what it is about, never by when it was drawn
status: accepted
date: 2026-09-20
deciders: ["punitarani", "claude"]
scope: ["py/src/jeve/world/**", "py/src/jeve/core/seed.py", "py/tests/test_world.py"]
tags: ["determinism", "randomness", "counterfactuals", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["CORE-0005", "WORLD-0002"]
confirmation: "cd py && uv run pytest tests/test_world.py"
---

# CORE-0009 — Randomness is keyed by what it is about, never by when it was drawn

## Context and Problem Statement

CORE-0005 made every random draw path-derived, so a run is reproducible. Six
paths in the world end in `tick_seq`: the outage hazard, which subscribers
notice an outage, invoice amounts, which clients think about paying, who walks
into the cafe, and where a person stands in a room. Reproducible, but not
*comparable*: the audit's counterfactual (`docs/audit/2026-09-21/README.md` B6,
A2) delayed month-end billing by 21.5 hours in one arm, and because the amount
of an invoice was drawn from the tick it was issued in, every invoice in that
arm was for a different amount. The experiment could not separate "the outage
made the money late" from "the outage re-rolled the money". Any two runs that
differ at all differ everywhere downstream, through the random numbers rather
than through the world.

## Considered Options

- **Leave it; compare distributions over many seeds.** Rejected: it turns every
  causal question into a statistics project, and the causal graph is the
  product.
- **Key by entity and by the entity's own calendar.** Taken.

## Decision Outcome

A seed path names the thing the draw is *about* and, where the thing recurs, its
own period: an invoice amount is `(issuer, client, billing month)`; whether a
subscriber notices an outage is `(person, incident)`; the hour a payer sits down
to their bills is `(person, day)`; the hazard is `(module, day, slot)`; where
someone stands is `(person, zone, arrival)`. `tick_seq` and event sequence
numbers never appear in a seed path, and a test walks the source to keep it so.

The same invoice is therefore the same amount whether it goes out on the 3rd or,
because of an outage, on the 4th. What differs between two arms of a
counterfactual is what the world did, not what the dice did.

### Consequences

- Good: counterfactuals are paired samples. "Cash differs, invoice amounts do
  not" becomes an assertion in the soak.
- Good: a slice of people acting "per tick" becomes each person acting at their
  own time, which also removes the `LIMIT n` windows that starved most
  counterparties of ever acting (audit B8).
- Bad: the golden run changes once, everywhere.
- Reverse it if: never. A draw that depends on the clock is a bug.
