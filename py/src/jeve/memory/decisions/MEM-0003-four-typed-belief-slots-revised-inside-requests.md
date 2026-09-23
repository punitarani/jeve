---
id: MEM-0003
title: Beliefs are four typed slots revised by score questions inside existing requests; relationships decay in SQL
status: accepted
date: 2026-09-22
deciders: ["claude"]
scope: ["py/src/jeve/memory/**", "py/migrations/0013_beliefs.sql", "py/tests/test_beliefs.py"]
tags: ["memory", "beliefs", "diffusion", "churn", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["MEM-0001", "DECIDE-0005", "WORLD-0009", "WORLD-0010", "CORE-0008"]
confirmation: "cd py && uv run pytest tests/test_beliefs.py"
---

# MEM-0003 — Beliefs are four typed slots revised by score questions inside existing requests; relationships decay in SQL

## Context and Problem Statement

MEM-0001 decided how memory would work — relational retrieval, typed belief
revision, compaction in SQL — and then nothing implemented it: every decision
was made from the present tick's facts, a person who lost a day to an outage
thought no less of the vendor the next morning, and word of a price rise
reached exactly the two people the supplier told. The district needed the
smallest layer that lets the past bear on a decision and lets a fact travel.

## Considered Options

- **A memory table of templated events with retrieval by entity join.** The
  full MEM-0001 design; more than any question here reads. Deferred, not
  refused.
- **A reflection call per agent per night.** The thing MEM-0001 exists to
  avoid. Loses.
- **Four slots, written by a score appended to a request that is being made
  anyway, read back as one sentence; relationships as a strength; facts as
  a copy at the moment of contact.** Taken.

## Decision Outcome

A belief is a level in one of four slots — `vendor_reliability`,
`employer_strain`, `counterparty_trust`, `knows_of` — held by a person about
an entity, revised only by a `score` asked inside `agent.tick`,
`ticket.confirm` or `chase.invoice`, and read back as the words of its level
into the next question it bears on; a relationship is a strength of one to
three that a conversation raises and a nightly SQL job lowers.

`jeve.memory.beliefs` is the whole vocabulary: the four slots with four
described levels each, `set_level`, `learn`, `words`, `firm_view`,
`bump_relationship`, `decay`. Writes: a reliability score when an outage is
on their mind or a ticket is confirmed; a strain score when their employer
held payroll or warned of insolvency this week; a trust score when a bill is
chased; `knows_of` set by code — noticing an outage, being told of one, or
hearing of a price rise over a conversation about money. Reads: strain at
level two or more joins what is on their mind; trust joins the chase; the
people they know best are offered sooner (DECIDE-0005); and at renewal a firm
whose loudest opinion of the vendor is level one or below is asked
`subscription.switch` when the other vendor sells the same category, once a
month — a yes moves the row and cites the last `incident.ended`. The rules
twin writes the same levels from the facts the model would be told.

### Consequences

- Good: the past reaches the present through four numbers per person per
  entity, and no call is made to remember anything.
- Good: diffusion is a copy at contact, so "who knew by when" is a query
  and the soak reports it.
- Bad: four slots is the ontology; a belief the schema lacks cannot form,
  and the churn rule (loudest opinion, once a month, half on rules) is a
  guess.
- Reverse it if: the belief-change rate is near zero after a month —
  levels too coarse — or the audit finds decisions that should have turned
  on a memory no slot holds.
