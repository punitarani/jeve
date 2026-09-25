---
id: "EVAL-0003"
title: "Judge arms on episodes of equal length"
status: "accepted"
date: 2026-09-24
deciders: ["claude"]
scope: ["py/src/jeve/evals/transcripts.py", "py/src/jeve/evals/cli.py", "py/tests/test_evals.py"]
tags: ["evals", "judge", "bias", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["EVAL-0001"]
confirmation: "cd py && uv run pytest tests/test_evals.py"
---

# EVAL-0003 — Judge arms on episodes of equal length

## Context and Problem Statement

EVAL-0001's judge compares an episode from one arm with an episode from
another, matched on what was at stake. The challengers that ran longer
conversations were all mildly dispreferred, and the one that ran shorter
conversations was preferred. That pattern fits a better arm, but it also fits
a judge that likes short accounts. The planted-defect test could not separate
the two, because none of its defects changes length alone.

## Considered Options

- **Measure the taste for length, then pair only accounts of the same shape.**
  Taken.
- **Correct afterwards by regressing verdicts on the length difference.** This
  needs a model of how length enters a verdict, and it spends verdicts on
  pairs whose difference is mostly length.
- **Tell the judge to ignore length.** An instruction is not evidence that the
  bias went away. It would still have to be measured, and matching is then
  simpler.

## Decision Outcome

Arms are judged only on pairs of the same shape: what was at stake, how many
rounds, and how many people. The planted-defect test also measures the
judge's taste for length.

`judge-validate` pairs each sampled episode with itself plus one unremarkable
round, placed before the last, in which the askers ask and the holders
explain. A judge indifferent to length scores 0.50. Measured on the
rules-twin worlds at 20261201–03, 20 pairs each, both orders counted
(`ops/evals/judge/0-validation*.json`), the shorter copy was preferred:

| Judge | Shorter copy preferred |
| --- | --- |
| GPT-5.6 Luna | 0.88 |
| Claude Haiku 4.5 | 0.93 |

This preference is as strong as the preference for a clean record over one
with a planted defect. So any comparison where one arm's conversations run
longer measures length as much as believability.

`transcripts.matched` pools same-shape pairs from each seed and draws among
them, so each shape is judged about as often as both arms produce it. Arm A/Bs
judged before this record matched on stake alone; they are re-judged, and
their files keep their names.

### Consequences

- Good: a difference in length can no longer pass for a difference in
  believability, in either direction.
- Bad: an episode with no partner of the same shape is not judged. Between
  GLM and Luna, over six 14-day seeds, matching on shape left 132 possible
  pairs where matching on stake alone left 165. It also
  means the judge cannot credit an arm for ending conversations at the right
  length. That question belongs to `episode_rounds_mean` and the
  settled/stalled shares, which are measured separately.
- What would reverse it: a judge that scores the padded copy within 0.40–0.60,
  on both judges, over at least 40 pairs.
