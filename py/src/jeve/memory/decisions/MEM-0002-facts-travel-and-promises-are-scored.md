---
id: "MEM-0002"
title: "Facts travel, promises are scored, and both are typed rows"
status: "accepted"
date: 2026-09-22
deciders: ["claude"]
scope: ["py/src/jeve/memory/**", "py/migrations/0009_episodes.sql", "py/tests/test_episodes.py"]
tags: ["memory", "knowledge", "diffusion", "commitments", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["MEM-0001", "WORLD-0006", "WORLD-0005", "GEN-0001"]
confirmation: "cd py && uv run pytest tests/test_episodes.py"
---

# MEM-0002 — Facts travel, promises are scored, and both are typed rows

## Context and Problem Statement

MEM-0001 accepted relational retrieval, typed belief revision and SQL compaction,
and none of it was built: `jeve/memory/` held the record and nothing else. That
was survivable while the only thing a meeting could change was the end of an
outage. WORLD-0006 ends that: an episode whose outcome has nowhere to go is
decoration, and two of the scenario's behaviours need state that did not exist —
diffusion through the cafe needs somewhere to write *who knows what*, and a
conversation about a bill needs somewhere to write *what was agreed*.

## Considered Options

- **`persons.beliefs`,** the jsonb column already in the first migration. No
  schema change, and no way to ask "who told whom", which is the measure.
- **MEM-0001 in full** — memories, importance, rollups, belief slots. The right
  eventual shape; most of it would have no reader, and a store with no reader
  drifts.
- **Three tables for the three things an episode can leave behind.** Taken.

## Decision Outcome

A **fact** is a thing that can be known and passed on, identified by what it is
about (`outage:<incident>`, `price_rise:<org>`) rather than minted from a counter,
so the same news is the same row in every arm of a counterfactual. **Knowledge**
records who holds it, from whom, and at what remove. A **commitment** is a promise
to pay a particular bill.

Four properties carry the weight. A fact **goes stale**: an outage that has ended
is gossip, not news, so it stops travelling and stops minting notices for an
incident nobody can be stuck on — without which the share of the town that knows
could only rise. `hops` **and the teller are one statement**, held together by the
database (`hops = 0` exactly when there is no teller), and a test walks the whole
graph so the measure cannot inflate itself. A promise **moves no money** — it
changes the state the payer's next decision is taken against, and the referee that
pays is still code (WORLD-0005) — and both policies see it, or the rules twin
stops being a control. A promise is **scored either way**: paying settles it kept,
the promised day passing unpaid settles it broken and says so.

Nothing here generates text or decides anything. A fact's words are rendered from
its topic by a question set on the way to the model and never read back
(GEN-0001).

### Consequences

- Good: behaviour #6 is measurable with no prose at all. Over 21 sim-days the
  seeded price rise reached 24 heads at up to seven removes, from one engineer.
- Good: word of mouth has a consequence, not just a counter — hearing a module
  you use is down brings your notice forward, so it reaches a ticket.
- Good: `reach_of` computes diffusion in SQL, so a report cannot disagree with the
  world.
- Bad: this is a third of MEM-0001 — no importance, retrieval, compaction or
  belief revision, so nothing reads the past except as facts and promises.
  Retention is unbounded, which is fine now and is not a plan.
- Bad: two topics only. A closed vocabulary cannot represent unanticipated news,
  the typed thesis' standing cost, measured as the ontology-gap rate.
- Reverse it if: belief slots arrive and a fact is better modelled as evidence for
  one — then `knowledge` becomes the evidence table under a new record rather
  than a parallel store.

Long form: `docs/design/011-episodes.md`.
