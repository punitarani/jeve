---
id: "EVAL-0002"
title: "Staff stay seeded; an LLM-written cast flattened them"
status: "accepted"
date: 2026-09-24
deciders: ["claude"]
scope: ["py/src/jeve/world/seed_world.py"]
tags: ["persona", "traits", "llm", "negative-result", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["EVAL-0001", "DECIDE-0003", "WORLD-0001"]
confirmation: null
---

# EVAL-0002 — Staff stay seeded; an LLM-written cast flattened them

## Context and Problem Statement

Every staff trait is drawn independently and uniformly (`traits_for`), so a
founder is as likely to be timid as a barista is to be litigious. The obvious
improvement — have a general-purpose model write each firm's staff as people
and compile what it writes to typed traits — was one of the brief's starting
hypotheses, cheap (four requests, $0.004, once), and safe under the thesis if a
referee types the output. The literature warned the other way: LLM personas
stereotype, compress toward the agreeable middle, and are hyper-rational
(docs/research/04 §3.5). A future engineer would plausibly build it; this
record says what happened when it was built.

## Considered Options

- **Keep the seeded draw.** Taken.
- **An LLM-written cast, compiled by a referee.** Built as an eval arm and
  measured: GLM 5.3 Flash described each firm's staff in one request, choosing
  low, middle or high per trait in the words Jev reads; a zero-LLM referee
  accepted only known ids and the three levels (144 of 144 set, none rejected)
  and placed each level inside its tertile by a keyed draw. The backstories were
  specific and plausible, and read by nothing.

## Decision Outcome

Staff traits stay seeded: the LLM-written cast lowered persona signal on
held-out seeds and bought nothing the judge could see.

What it wrote leaned diligent (14 of 24 staff "high", against 6 seeded) and
middling in voice (13 of 24 "middle" for vocality). On three held-out seeds,
paired against the seeded cast (`ops/evals.md`): persona signal −0.050
[−0.067, −0.038], d_z −3.2; action entropy −0.019 [−0.029, −0.006]; stalled
conversations +0.17 [+0.08, +0.31]. The judge preferred its episodes 12 times
in 23 on dev seeds and 14 in 22 on held-out ones — an interval that includes
indifference both times. The code was removed; the runs are kept.

### Consequences

- Good: persona stays as wide as the seeded ranges make it.
- Bad: people's traits are still uncorrelated with their jobs; if role
  coherence matters, it has to come from somewhere other than a model's idea of
  a typical accountant.
- Reverse if: a cast written against an explicit spread (the seeded marginals
  as a constraint the referee enforces) matches the seeded arm's persona signal
  and a judge prefers it on held-out seeds.
