---
id: DECIDE-0003
title: Question sets in words, J/P/H resolution, and a content-hash call cache
status: accepted
date: 2026-09-20
deciders: ["claude"]
scope: ["py/src/jeve/decide/questions.py", "py/src/jeve/decide/sampling.py", "py/src/jeve/decide/recorder.py", "py/src/jeve/decide/jev_policy.py", "py/fixtures/cassettes/**"]
tags: ["jev", "sampling", "replay", "economics", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["DECIDE-0001", "DECIDE-0002", "CORE-0005", "CORE-0007", "WORLD-0001", "LLM-0004"]
confirmation: "cd py && uv run pytest tests/test_questions.py tests/test_sampling.py tests/test_jev_policy.py"
---

# DECIDE-0003 — Question sets in words, J/P/H resolution, and a content-hash call cache

## Context and Problem Statement

`JevPolicy` had to be written against the `Policy` seam with three things
settled: what is sent to Jev, how an answer becomes an action, and how a run is
made repeatable when the model has no seed. Each has a quiet failure mode.
Numbers in the state degrade Jev's answers. Taking the argmax of a disposition
makes every impatient customer the same person. And a cache keyed on anything
unstable replays nothing.

## Considered Options

- **Send the raw context** (traits as floats, counts as integers). Least code.
  Jev reads literally and is weak at arithmetic; and no two people would ever
  share a request, so every decision is a paid call. Loses.
- **Argmax everything.** Deterministic without a PRNG. It is also the
  persona-flattening failure the project exists to test for. Loses.
- **Sample everything.** A ticket about a broken export would sometimes be
  routed to billing. Judgements have right answers. Loses.
- **Cassette keyed by call order** (VCR-style). Breaks the moment one decision
  is added anywhere upstream. Loses to a content hash.
- **Words, tagged J/P/H, cached by content hash.** Taken.

## Decision Outcome

State is rendered in words with traits bucketed into tertiles of their seeded
range; every question is tagged J (argmax), P (sampled) or H (a day-level
propensity thinned to a per-tick hazard); hard constraints are code gates that
never reach the model; and every call is cached in `model_calls` by the content
hash of `(model, state, questions)`, mirrored to a sorted JSONL cassette.

Sampling iterates the **declared** option order, never the response's: JSONB
and providers both reorder keys, and a replayed call must draw exactly as the
live one did. For the same reason a decision is always made from the *stored*
row, including on the call that created it — one code path, not two that can
disagree. The draw comes from the path-derived PRNG (CORE-0005) keyed by person
and decision sequence, so two people in an identical situation share a
distribution and a bill, and still behave differently.

H exists because "will they pay today?" asked every fifteen minutes and sampled
each time compounds to near-certainty by lunch: `1-(1-p)^32`. Jev cannot do that
arithmetic, so code does: `h = 1-(1-p)^(1/32)`.

Strict replay never constructs a `Gateway` and treats a miss as an error naming
the question set. It does not fall back to rules: a replay that quietly swaps
the decider is not a replay.

Measured on 2026-09-20: the five-day fixture made 1,163 model decisions from 54
distinct calls. `ops/persona-probe.md` shows the bucketed traits move Jev's
distributions by 500x to 6,000x its noise floor in all six test cases, and
leave the control flat.

### Consequences

- Good: `make e2e` is free and keyless on a clean clone, and byte-reproducible.
- Good: cost scales with distinct *situations*, not with population.
- Bad: tertile bucketing throws information away. Two people at 0.31 and 0.49
  patience are the same person to Jev. Persona survives between buckets, not
  within them.
- Bad: wording is frozen. Editing a sentence in a question set re-records every
  call that contained it, and changes the run.
- Bad: the unit-economics figure is dominated by sharing. The report therefore
  also prices every decision as its own call and judges the targets against
  that, so they are not met on the strength of the cache.
- Bad: Jev's base rates are taken as given (a patient customer at an empty
  counter buys with p=0.84). The probe shows traits are load-bearing, not that
  magnitudes are true.
- Reverse it if: a finer trait resolution is shown to matter for an emergent
  behaviour, or Jev gains a seed (then sampling could move server-side).
