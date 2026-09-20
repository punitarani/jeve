---
id: DECIDE-0001
title: Send one request per decision point carrying the whole decision surface
status: accepted
date: 2026-09-20
deciders: ["punitarani"]
scope: []
tags: ["jev", "batching", "questions"]
supersedes: []
superseded-by: null
relates-to: ["CORE-0002", "DECIDE-0002"]
confirmation: null
---

# DECIDE-0001 — Send one request per decision point carrying the whole decision surface

## Context and Problem Statement

Jev bills the state once per request and evaluates every question in parallel;
TypeSafe measures 13 questions in one call as 12× cheaper and 10× faster than
13 calls. More fundamentally, questions in a request are *independent* — one
answer is never context for another — so there is nothing to sequence. The open
question was the cadence: per tick, or per something else.

## Considered Options

- **One question per call** — the habit coding agents fall into. 10× the
  latency, 12× the cost.
- **One call per agent per tick.** Rejected: an agent halfway through a
  two-hour task has no decision to make, and asking anyway is both wasteful and
  behaviourally wrong.
- **One call per agent per *decision point*.** Taken.

## Decision Outcome

An agent is evaluated only at a decision point — task complete, inbox item over
an importance floor, schedule boundary, synchronous interaction, or a mandatory
timer — and that one request carries every question the role might need.

Question sets compose from four layers (base, role, org policy, situational);
the situational layer is what keeps requests small, since parameter questions
for a verb are included only when that verb is possible. Org policy is *data*,
which is how one org's rules change without touching another's.

Questions are of two kinds and the kind decides what code does with the answer:
**judgment** questions are thresholded, **propensity** questions are *sampled*
from the returned distribution. Propensity questions about irreversible acts
(resign, churn, dispute) fire only at event-triggered decision points and pass
through hysteresis, because sampling a 2% propensity at every wake makes it a
near-certainty within a week — the hazard-rate trap.

### Consequences

- Good: cost scales with decisions made, not ticks elapsed.
- Good: every verb choice carries an `other` option, and mass on it is logged
  as an ontology gap — the project's primary research measurement.
- Bad: a linter is now load-bearing (no arithmetic, no date comparison, no
  dependent questions, described score levels), because Jev reads literally.
- Reverse it if: latency rises materially past ~30 questions, or answers shift
  when unrelated questions are added.

Long form: `docs/design/004-question-sets.md`.
