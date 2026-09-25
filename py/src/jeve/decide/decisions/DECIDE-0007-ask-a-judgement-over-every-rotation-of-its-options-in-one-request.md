---
id: "DECIDE-0007"
title: "Ask a judgement over every rotation of its options, in one request"
status: "accepted"
date: 2026-09-24
deciders: ["claude"]
scope: ["py/src/jeve/decide/jev_policy.py", "py/src/jeve/sim/panel.py", "py/tests/test_rotations.py", "py/scripts/prompt_lab.py"]
tags: ["jev", "robustness", "position-bias", "typed-decisions", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["DECIDE-0001", "DECIDE-0003", "DECIDE-0004", "DECIDE-0005"]
confirmation: "cd py && uv run pytest tests/test_rotations.py"
---

# DECIDE-0007 — Ask a judgement over every rotation of its options, in one request

## Context and Problem Statement

A judgement (J mode) over a choice takes Jev's argmax. On real states from six
60-day worlds, reversing a judgement's options (keeping `other` last) flipped
Jev's verdict in 15% of credit decisions (34 states), 22% of engineering
allocations and 11% of founder reviews (9 each). The
firm's decision depended partly on how its options were listed, not only on
the situation. A propensity (P mode) is sampled, so its position bias only
shifts a distribution. A judgement's position bias can flip the verdict.

## Considered Options

- **Every cyclic rotation, as suffixed copies of the question in the one
  request, averaged before the argmax.** Taken.
- **Declared and reversed order only.** Rejected: it halved the flips on an
  unseen order for some sets and not others (8.0% to 5.4% pooled).
- **The same rotations as separate requests.** As good (3.1%), but a decision
  row keeps one call hash, so cost accounting would miss the others.
- **Leave it.** Rejected: 7% of verdicts changing with an unseen order is not
  a decision about the situation.

## Decision Outcome

Each judgement over a choice is asked once in its declared order and once more
per other cyclic order of its options (`key__r1`, `key__r2`, ...), in the same
request; the copies are averaged back into one answer under its own key.

The test was an order the method never saw: every rotation of the reversed
list, in a request shaped as production sends it (`prompt_lab.py orders`,
six worlds). Across 350 states in eight judgement sets, averaged verdicts
disagreed with it in 3.7% of states. A single order, against another,
disagreed in 6.9%. Supplier orders went from 18% to 2%, engineering
allocation from 12% to 2%, dispute resolution from 7% to 0%. Founder review
(10% to 12%) and credit (2.5% to 6%) did not improve: their flips are
near-ties, a handful of states either way. Sharing a request moved an order's
own answer by 0.01–0.04 (total variation). `ops/evals/prompt-lab/` has the
runs.

### Consequences

- Good: judgements depend on the situation, not on list position. The call
  count and the cache are unchanged: one request per decision.
- Bad: judgement requests are longer (k copies of a 3–5 option question), and
  every judgement set's bytes changed, so the cassettes re-record.
- Reverse if: a Jev build shows no position bias on the same test. Then one
  order is enough and the copies are wasted tokens.
