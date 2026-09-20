---
id: DECIDE-0002
title: Escalate on confidence in two tiers, and keep the first tier typed
status: accepted
date: 2026-09-20
deciders: ["punitarani"]
scope: []
tags: ["escalation", "confidence", "routing"]
supersedes: []
superseded-by: null
relates-to: ["DECIDE-0001", "LLM-0002"]
confirmation: null
---

# DECIDE-0002 — Escalate on confidence in two tiers, and keep the first tier typed

## Context and Problem Statement

A calibrated probability is only useful if code does something different when
it is low. But "low confidence" is not one number here: `noul` returns no
confidence field at all, and TypeSafe documents that a threshold tuned on one
primitive must not be carried to another.

## Considered Options

- **One global confidence threshold.** Contradicts the vendor's own docs and
  ignores stakes.
- **Escalate to prose** — ask a smart model what to do. Rejected: it returns
  text that must be parsed back into the ontology, reintroducing the failure
  class this project exists to remove.
- **Self-consistency voting on Jev.** Rejected: its repeat variance is ~0.01,
  so N calls return the same answer N times.
- **Two tiers, the first still typed.** Taken.

## Decision Outcome

Tier 1 re-asks only the uncertain questions of a flash LLM through TypeSafe's
adapter, which returns the same typed response shape; tier 2 is generative and
fires only on an ontology gap or when a viewer needs prose.

Uncertainty is defined per primitive: a `choice` by confidence or top-two
margin unless both options are in the same consequence class; a `score` only
when the distribution actually straddles the boundary code uses; a `noul` by a
band around *that question's* action threshold, not around 0.5.

**Propensity questions escalate only when the stakes are high.** A flat
distribution over plausible next actions is what indecision looks like, and
sampling is the correct response. Routing every flat propensity to an LLM would
send the most human decisions to the model most prone to collapsing them to one
mode, destroying the diversity the sampling exists to produce.

Thresholds are placeholders until tuned: offline against recorded contexts, then
online in shadow mode with a uniform 2% sample so the estimate is unbiased.

### Consequences

- Good: escalation does not change the shape of the answer, so nothing downstream
  knows or cares which model answered.
- Bad: what this measures is agreement with an LLM panel, not correctness.
- Reverse it if: disagreement turns out to be uncorrelated with confidence, in
  which case gate on stakes alone.

Long form: `docs/design/005-escalation.md`.
