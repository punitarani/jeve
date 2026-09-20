# ADR-006 — Memory over unbounded time

Status: proposed · 2026-09-20

## Context

Neither reference system forgets. Smallville stamps thoughts with a 30-day expiry that
nothing enforces; Concordia's memory bank says in a docstring that "memories cannot be
deleted", and its basic prefab sets history length to 1,000,000, so prompts grow linearly per
act (01 §2). Both were built to run for days. jeve produces ≈ 3 sim-years per real month
(ADR-001).

Two facts shape the design. Jev degrades on large irrelevant state (00 §1.6), so whatever
reaches a request must be small and pertinent. And jeve's world is typed: every event carries
entity ids. **Relevance is mostly a join, not a similarity search.**

## Decision

### Store

`memories` rows (ADR-009): agent, sim time, kind (`observation`, `interaction`,
`commitment`, `belief_change`, `rollup`), entity refs, source event, importance level, tier
(`hot`, `cold`), last retrieved. The text of a memory is **templated from its event** — never
generated.

### Importance — Jev, with a code floor

A rule assigns a floor by event kind (an outage notice is never trivial). Above the floor,
one Jev `score` per new inbox item with four *described* levels — routine / notable /
consequential / pivotal — asked in the same request as the decision surface, since the items
are already in `state`. No extra call. J-type.

### Retrieval — code

`score = recency × importance × (1 + relational relevance)`

- *Recency:* exponential decay in **sim-hours**, half-life per kind. (Smallville decays over
  rank, not time, and as written appears to rank the oldest highest, 01 §2.)
- *Relational relevance:* overlap between the memory's entity refs and the entities in the
  current situation.
- Top 8, hard cap 600 tokens in `state`.
- **No embeddings in the MVP.** workbench runs without them (00 §6.5) and its prompts stayed
  flat across 140 sim-days.
- *Jev rerank* only when the relational filter returns more than fit: one `choice` whose
  options are the candidate ids, giving a relevance distribution in a single question. It is
  a genuine second request (ADR-004), so it is the exception.

### Reflection — typed belief revision

Trigger in code: accumulated importance per (agent, entity) crosses a threshold, plus a
sim-daily floor. Focal points in code: the entities with the most new high-importance
memories. Then, per (belief dimension, entity) slot in the role's schema — reliability,
trust, price fairness, own workload strain — **one Jev `score` over the evidence memories**.
Commitments are extracted by `noul` per candidate commitment kind. Changes are written to
`belief_history`. J-type throughout.

Beliefs are small, typed, and always in `state`. They are how the distant past influences the
present after the memories behind it are gone. AGA made the equivalent move — typed
relationship keywords replacing ~2,000 tokens of retrieved events — and it alone cut tokens to
58.6% (01 §5).

### Compaction and forgetting — code

Nightly in sim time, per (agent, entity):

1. Memories older than 5 sim-days are folded into a **rollup computed by SQL aggregation** —
   "d1–d14: 14 invoices from Ledgerline; 2 late; 1 disputed." Not a generated summary.
2. Source rows move to `cold`.
3. Cold rows are deleted after 30 sim-days **unless** pivotal, or referenced by an open
   commitment.
4. A per-agent cap of 2,000 live rows evicts by lowest `importance × recency`.

Nothing is lost that matters to analysis: the event log is permanent (ADR-009). Memory is
what an *agent* can recall; the log is what *we* can.

Steady state ≈ 24 agents × ~40 memories per agent-day × 30 days ≈ 29k live rows. Trivial.

### What generation does

Nothing in the loop. Two optional uses, both outside it: **ontology extension** — weekly, an
LLM proposes new belief slots or goals as structured data for review (01 §3) — and a
viewer-facing diary rendered from the typed record.

## Summary of who does what

| Part | Done by |
|---|---|
| Importance scoring | Jev `score`, batched, with a rule floor |
| Relevance | SQL join; Jev rerank only on overflow |
| Recency, top-k, caps | Code |
| Reflection trigger, focal points | Code |
| Belief revision, commitment extraction | Jev `score` / `noul` |
| Compaction | SQL aggregation |
| Forgetting | Code |
| New concepts | LLM, rare, reviewed |

## Alternatives rejected

- **Smallville's generated reflections.** 34 LLM calls per reflection, 6–9 reflections per
  agent-day (01 §2); the insights re-enter retrieval as prose, which becomes unfiltered state
  for a model documented as steerable by its state. Costly and a contamination path.
- **Generated rolling summaries** (Lyfe's summarize-and-forget). Reasonable, but summaries
  drift, and a drifted summary is permanent. An SQL rollup cannot hallucinate.
- **pgvector from day one.** Adds an embedding model, a second cost line, and a
  nondeterminism source, to find things the entity graph finds exactly.
- **Keep everything, retrieve harder.** Retrieval quality degrades with store size — the one
  long-horizon failure Smallville's authors name themselves.

## What this costs

Agents cannot form a concept their slot schema lacks. "Klaus is dedicated to his research"
has no slot. This is a genuine limit of the typed thesis and is measured, not hidden: the
ontology-gap rate, and whether agents adapt to a regime change no slot anticipated (01 §4).

## Reverse if

- Agents forget live commitments (commitment-miss rate, from the log) → pin
  commitment-linked rows until the commitment closes; lengthen retention.
- Sampled audits show relational retrieval missing memories that are related in meaning but
  share no entity → add pgvector as a third candidate source.
- Belief slots stop moving (belief-change rate → 0) → levels are too coarse; rewrite them.
