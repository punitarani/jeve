---
id: "EVAL-0001"
title: "An LLM role is kept only on a held-out, judged, paired A/B"
status: "accepted"
date: 2026-09-24
deciders: ["claude"]
scope: ["py/src/jeve/evals/**", "py/scripts/evals.py", "py/tests/test_evals.py", "py/tests/test_layering.py"]
tags: ["evals", "measurement", "llm", "layering", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["CORE-0008", "CORE-0009", "API-0004", "DECIDE-0005", "DECIDE-0006", "SIM-0001"]
confirmation: "cd py && uv run pytest tests/test_evals.py tests/test_layering.py"
---

# EVAL-0001 — An LLM role is kept only on a held-out, judged, paired A/B

## Context and Problem Statement

The brief was to add general-purpose LLMs where they *measurably* help. jeve had
single-question probes (`persona-probe`, `situation-probe`, `judge-panel`), a
two-arm episodes study on rules, and the field report's detectors — but no way
to say that an arm with a model in it is more realistic than one without, with
the variance of that claim. Without one, every role is kept on its demo, and
the literature says LLM judges and single runs both flatter what they measure
(docs/research/04 §3).

## Considered Options

- **A harness package outside the layers that runs arms over seeds and scores
  them four ways, with a judge that must first catch planted defects.** Taken.
- **Measurement inside `jeve.sim`, as the soak and the episodes study are.**
  Rejected: the harness needs the field report's detectors, and `sim` may not
  import `api` (CORE-0008). Copying the detectors would give two definitions of
  "persona signal".
- **Believability by an LLM judge on generated dialogue.** Rejected: a judge
  prefers fluent prose, so it would score the renderer, not the behaviour.
- **One seed per arm.** Rejected: the dev seeds alone show seed-to-seed spreads
  larger than several effects.

## Decision Outcome

An LLM role is kept only when its held-out, paired-by-seed contrast against the
arm without it shows a gain and no clear loss, and a judge that has passed a
planted-defect test prefers it.

`jeve.evals` is the outermost package: it drives `sim`'s one run loop, reads
`api`'s detectors, calls models through `llm`, and nothing imports it — the
layering test says so. Each (arm, seed) runs on a database of its own through
`daemon.main`, preloaded with every cassette already recorded, so a prompt
costs money once. Four kinds of number:

- **plausibility** — stylized facts against cited real-world bands, PASS, FAIL
  or ABSENT (`priors.py`);
- **depth** — persona signal, identifiability, episode closure, diffusion,
  memory, from the same detectors the live report uses;
- **believability** — GPT-5.6 Luna, a family no role under test uses, compares
  episodes rendered from typed records by one fixed template, both orders; any
  episode a round of which its own family answered is excluded;
- **non-regression** — the soak's invariants at the horizon, an event-log
  digest (same seed, same world), and cold-cache cost per sim-day.

Dev seeds are used while a role is built; the held-out seeds decide.

### Consequences

- Good: a role's claim is a number with an interval, reproducible from JSON in
  `ops/evals/runs/` for nothing; the judge is itself tested (0.98 on planted
  defects, 0.50 on identical pairs, 50/50 on retest).
- Good: the harness found, before any role was added, that Jev's conversations
  stall (2% end settled on dev seeds) and that the world's bills are paid about
  on time where real ones are 8 days late.
- Bad: three held-out seeds of seven sim-days is a small sample; monthly facts
  (churn, turnover) are ABSENT at that horizon, and the judge's planted defects
  are blatant ones — passing them shows it can see a broken account, not that
  it can rank two plausible ones finely.
- Reverse if: a role the harness rejected is shown by a longer or human-judged
  study to help, or the judge's arm verdicts stop agreeing with the depth
  measures they should move with.
