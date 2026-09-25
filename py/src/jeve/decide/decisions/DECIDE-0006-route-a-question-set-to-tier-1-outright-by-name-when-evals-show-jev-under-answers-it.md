---
id: "DECIDE-0006"
title: "Route a question set to tier 1 outright, by name, when evals show Jev under-answers it"
status: "accepted"
date: 2026-09-24
deciders: ["claude"]
scope: ["py/src/jeve/decide/escalation.py", "py/src/jeve/decide/jev_policy.py", "py/src/jeve/config.py", "py/src/jeve/sim/runner.py", "py/tests/test_escalation.py"]
tags: ["escalation", "llm", "episodes", "typed-decisions", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["DECIDE-0002", "DECIDE-0005", "EVAL-0001", "WORLD-0008", "LLM-0006"]
confirmation: "cd py && uv run pytest tests/test_escalation.py"
---

# DECIDE-0006 — Route a question set to tier 1 outright, by name, when evals show Jev under-answers it

## Context and Problem Statement

Tier 1 (DECIDE-0005) re-asks a flash LLM only where Jev was unsure, never for a
low-stakes propensity: design/005's "single most consequential line", because
an LLM would collapse a flat distribution and flatten persona. So nothing could
ask whether a general-purpose model answers a whole set *better* — and the
first eval sweep (EVAL-0001) found a set it might. Under Jev, conversations do
not end: on six held-out seeds 0% of episodes settled and 48% went round in
circles (the rules twin settles 92%), and a judge from another family preferred
the rules twin's episodes in 35.5 of 46 pairs. Jev puts 0.29 on "I have had my
say" and little on leaving, so the same acts repeat until the stall rule ends
them.

## Considered Options

- **Route the whole `episode.round` set to tier 1, by name.** Taken.
- **Route only `done`** (`episode.round:done`). Rejected on dev seeds: settled
  0.32, stalled 0.34, judge 0.47, twice the cost — the repetition is in the acts.
- **Tier 1 `live` everywhere DECIDE-0005 allows.** Not adopted: on held-out
  seeds it changed nothing but cost; judge 0.43 (n = 22).
- **Reword `done` and the acts for Jev.** Not measured. Open.

## Decision Outcome

`JEVE_ESCALATION_ROUTE` names sets — or single questions, as `set:ask` — that
tier 1 answers outright in Jev's typed shape, sampled from the LLM's own
distribution; it defaults to `episode.round`.

Typed end to end: Jev's state and questions, a strict schema, the draw outside
the model on the same seeded path, the reply cached by the bytes sent
(DECIDE-0004) — a replay gave the identical event-log digest with no key. Jev
is still asked; both answers land in `escalations` with the trigger `routed`,
which the day's tier-1 room ignores. No generated text is read by the world.

What overrides design/005 here (six held-out seeds, 513 decisions answered
by both):

| | Jev | routed |
| --- | ---: | ---: |
| normalised entropy of the act, per decision | 0.51 | 0.81 |
| P(had their say) | 0.29 | 0.52 |
| gap in P(press), outspoken minus quiet | +0.40 | +0.16 |
| gap in P(small talk), sociable minus reserved | +0.39 | +0.29 |

The LLM spread the distribution rather than collapsing it; persona survives in
direction and weakens, sharply on pressing.

### Consequences

- Good (six held-out seeds, paired, `ops/evals.md`): settled +0.59 [+0.54,
  +0.64]; stalled −0.40 [−0.53, −0.25]; no banded plausibility fact,
  invariant or world-level persona signal moved. The judge preferred routed
  episodes in 36 of 48 pairs and put them level with the rules twin's (0.48).
  News heard second-hand rose on the first three seeds and not over six.
- Bad: the decision bill goes from $0.0039 to $0.0176 a sim-day; talking ticks
  wait ~8 s per round call (CORE-0004: slow model, slow world); pressing
  flattens by persona. GLM 5.3 Flash answered 78% of routed decisions — 17% of
  its replies were reasoning text, not JSON, and fell through to Gemini at
  several times the price (`docs/ops/llm-integration.md`).
- Reverse if: Jev, reworded, ends conversations at a similar rate; a week of
  shadow comparison shows a plausibility fact pushed out of band; or the cost
  binds against CORE-0002. Off: `JEVE_ESCALATION_ROUTE=off`.
