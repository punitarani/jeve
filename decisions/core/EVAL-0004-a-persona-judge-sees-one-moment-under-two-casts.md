---
id: "EVAL-0004"
title: "A persona judge sees one moment under two casts"
status: "accepted"
date: 2026-09-25
deciders: ["claude"]
scope: ["py/src/jeve/evals/casts.py", "py/src/jeve/evals/cli.py", "py/src/jeve/evals/judge.py", "py/scripts/prompt_lab.py", "py/tests/test_evals.py"]
tags: ["evals", "judge", "persona", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["EVAL-0001", "EVAL-0003", "DECIDE-0006"]
confirmation: "cd py && uv run pytest tests/test_evals.py"
---

# EVAL-0004 — A persona judge sees one moment under two casts

## Context and Problem Statement

The laboratory found that GLM, which answers routed conversations, flattens
people. On the same routed decisions, Jev's P(press) rose 0.36 from the
quietest third of people to the most outspoken third, and GLM's rose 0.16.
Luna kept more of that gradient, but EVAL-0001's judge did not prefer Luna's
worlds, even on episodes of equal length (EVAL-0003).

That judge cannot see persona. It reads one encounter at a time, and persona
is a difference between people: a judge never shown a quiet person beside a
loud one in the same moment cannot tell a model that keeps them apart from one
that does not. Whether persona fidelity is worth anything could not be
decided with the instrument we had.

## Considered Options

- **One moment, two casts, side by side.** Taken. Each side shows the same
  real moment twice, once with the person deciding described as outspoken and
  sociable and once as quiet and reserved, and what that person did in each.
  The judge is asked which side's behaviour fits the person described and the
  situation.
- **Score the gradient and skip the judge.** The laboratory already measures
  the gradient. A model can raise it by caricature, and the tuned tier-1
  prompt did exactly that (docs/ops/llm-integration.md). A judge is the
  independent check that the difference is plausible.
- **Tell the ordinary judge to weigh persona.** It already is told to. The
  problem is what it is shown, not what it is asked.

## Decision Outcome

Persona is judged on one moment under two casts. The judge must first catch
planted flattened and swapped casts on real moments, at `MIN_ACCURACY` or
better.

The words on each side are the ones the deciding model was given, from the
state its question was prepared with. The acts come from the typed records.
Planted defects use moments where the right act is plain: an asker who is
held up, or a bystander. The clean side has the outspoken version push or
chat and the reserved version break off. *Flattened* gives both versions one
act. *Swapped* gives each the other's act.

Validation on 60 moments from the rules-twin worlds at 20261201–03, 20 per
kind, both orders counted (`ops/evals/judge/0-validation-casts*.json`):

| Judge | Caught | Flattened | Swapped | Identical |
| --- | --- | --- | --- | --- |
| GPT-5.6 Luna | 0.975 | 0.975 | 0.975 | 0.50 |
| Claude Sonnet 5 | 0.95 | 0.975 | 0.925 | 0.50 |
| Claude Haiku 4.5 | 0.61 | 0.55 | 0.675 | 0.50 |

Haiku mostly followed position and is not used as a persona judge. The
persona jury is Luna and Sonnet. As everywhere, a judge never scores an arm
from its own family, so a contrast involving Luna is judged by Sonnet alone.

### Consequences

- Good: a model that keeps people distinct can now be credited for it by an
  instrument that can also refuse the credit.
- Bad: planted cases are easier than real ones. A real arm's two versions
  often do the same thing by chance, and those pairs count as ties.
- What would reverse it: a judge that prefers a caricatured cast (an
  outspoken person pressing a bystander's matter, say) over a plausible one,
  or a validation run that falls below `MIN_ACCURACY`.
