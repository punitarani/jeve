---
id: "DECIDE-0008"
title: "A routed propensity takes the person from Jev"
status: "accepted"
date: 2026-09-25
deciders: ["claude"]
scope: ["py/src/jeve/decide/jev_policy.py", "py/src/jeve/decide/escalation.py", "py/src/jeve/decide/questions.py", "py/tests/test_escalation.py", "py/scripts/prompt_lab.py", "py/scripts/persona_gradients.py"]
tags: ["escalation", "persona", "typed-decisions", "llm", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["DECIDE-0006", "EVAL-0001", "EVAL-0004"]
confirmation: "cd py && uv run pytest tests/test_escalation.py"
---

# DECIDE-0008 — A routed propensity takes the person from Jev

## Context and Problem Statement

DECIDE-0006 routes conversations to GLM, because Jev never lets people finish
one, and samples GLM's own answer. GLM flattens people. On the same routed
decisions, the most outspoken third pressed with probability 0.29 higher than
the quietest third by Jev's answer, but only 0.16 higher by GLM's. Changing
the model or its prompt did not fix this: the tuned prompt was Goodharted,
and Luna cost 30% more with no preference from the ordinary judge. Each tier
is good at something different. Jev keeps people distinct, and GLM follows a
conversation.

## Considered Options

- **The LLM asked about the average person, moved by Jev's ratio for this
  person over the average one, on propensities only.** Taken.
- **The same on every routed answer, judgements included.** Tried. It moved
  whether someone had had their say, a judgement GLM was routed to make.
  P(done) fell from 0.65 to 0.58, conversations settled less (0.84 to 0.72),
  and they ran a third of a round longer.
- **Luna in place of GLM.** Luna keeps more persona on its own. The persona
  judge (Sonnet) preferred GLM with Jev's person over Luna, 0.56
  [0.48, 0.65], at no extra LLM cost.
- **An even mixture of both answers.** It halves both effects.

## Decision Outcome

For a routed set, Jev is asked about this person and about the same situation
with every trait at the middle of its range, in the same batch. Tier 1 is asked
about that average person. A judgement is the LLM's whole, so `done` is read
off the conversation for the average person. A propensity is the
LLM's answer times Jev's ratio for this person over the average person,
renormalised (`escalation.transplant`, with a 0.01 floor on Jev's side). This
amends DECIDE-0006's "sampled from the LLM's own distribution" for
propensities only.

A log-linear model: in log-odds the persona effect is Jev's in full; in
probability it is smaller wherever GLM's average-person baseline is lower.

Evidence, all committed:

- **Prompt lab** (held-out states, counterfactual trait low→high,
  `ops/evals/prompt-lab/transplant.json`): press by outspokenness 0.16 → 0.22,
  small talk by sociability 0.13 → 0.26, P(done) 0.55 unchanged.
- **Persona judge** (EVAL-0004; 60 held-out moments × 2 draws,
  `ops/evals/prompt-lab/casts.json`): transplanted acts over GLM's, Sonnet 0.62
  [0.53, 0.70] and Luna 0.57 [0.48, 0.66]. GLM's own acts against Jev's: Sonnet
  0.43, Luna 0.48.
- **World A/B** (six 14-day dev worlds against plain GLM,
  `ops/evals/runs/rounds_*`, `ops/evals/prompt-lab/transplant-world.json`):
  applied press gradient 0.16 → 0.32 and small-talk gradient 0.19 → 0.27, where
  Jev's own on the same decisions were 0.39 and 0.38. Stalled conversations
  0.042 → 0.006 and rounds 1.38 → 1.21, both clear; settled 0.84 → 0.91, not
  clear. Cost unchanged. The ordinary judge, on equal-length episodes: Luna 0.55
  [0.47, 0.62], Haiku 0.55 [0.47, 0.62].

### Consequences

- Good: persona survives routing, with no extra LLM call and closure intact.
  The LLM's request no longer depends on who the person is, so two people in
  one situation share it.
- Bad: one more Jev call per routed decision whose person is not average. The
  identifiability ratio fell (38 → 31, clear). Distinctness between people was
  unchanged (0.238 → 0.232). What rose was each person's own variety of
  topics (retest JSD 0.147 → 0.183), as more news travelled. The
  probability-scale gradients reach about 70–85% of Jev's, not all of them.
- What would reverse it: a persona judge that prefers plain GLM's acts, or a
  world in which the transplanted acts contradict their situations (an
  ontology-gap rise, or the ordinary judge preferring plain GLM at equal
  length).
