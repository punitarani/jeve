---
id: MEM-0001
title: Retrieve memory relationally, revise beliefs typed, and compact in SQL
status: accepted
date: 2026-09-20
deciders: ["punitarani"]
scope: []
tags: ["memory", "retrieval", "beliefs"]
supersedes: []
superseded-by: null
relates-to: ["DECIDE-0001", "CORE-0003"]
confirmation: null
---

# MEM-0001 — Retrieve memory relationally, revise beliefs typed, and compact in SQL

## Context and Problem Statement

Neither reference system forgets. Smallville stamps thoughts with an expiry
nothing enforces; Concordia's memory bank says outright that memories cannot be
deleted, and its default prefab keeps a million entries, so prompts grow
linearly per act. Both were built to run for days. This world produces roughly
three sim-years per real month, and Jev's accuracy degrades as irrelevant state
grows.

## Considered Options

- **Smallville's generated reflections.** 34 LLM calls per reflection, 6–9
  reflections per agent-day, and the insights re-enter retrieval as prose —
  costly, and a contamination path into a model documented as steerable by its
  own state.
- **Generated rolling summaries.** Reasonable, but a drifted summary is permanent.
- **pgvector from day one.** Adds an embedding model, a cost line and a
  nondeterminism source to find what the entity graph finds exactly.
- **Relational retrieval, typed belief revision, SQL rollups.** Taken.

## Decision Outcome

Relevance is a join over typed entity references rather than a similarity
search; importance and belief revision are Jev `score` questions batched into
the decision request; and compaction is SQL aggregation, not generation.

Memory text is templated from its event and never generated. Beliefs are small
typed slots — reliability, trust, price fairness, workload strain — which is
how the distant past keeps influencing the present after the memories behind it
are gone. Nightly, memories older than five sim-days fold into a rollup
computed by aggregation, which cannot hallucinate; cold rows are deleted after
thirty sim-days unless pivotal or referenced by an open commitment.

Nothing is lost that matters to analysis: the event log is permanent. Memory is
what an agent can recall; the log is what we can.

### Consequences

- Good: importance scoring costs no extra call — the items are already in state.
- Good: live rows plateau (~29k at 24 agents), so prompts stay flat.
- Bad: agents cannot form a concept their slot schema lacks. "Klaus is
  dedicated to his research" has no slot. This is a real limit of the typed
  thesis and is measured as the ontology-gap rate rather than hidden.
- Reverse it if: audits show relational retrieval missing memories that are
  related in meaning but share no entity — then add pgvector as a third source.

Long form: `docs/design/006-memory.md`.
