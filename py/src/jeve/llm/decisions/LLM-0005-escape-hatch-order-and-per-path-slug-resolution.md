---
id: LLM-0005
title: Escape-hatch order and per-path slug resolution
status: superseded
date: 2026-09-20
deciders: ["claude"]
scope: ["py/src/jeve/llm/catalog.py", "py/src/jeve/llm/gateway.py", "py/scripts/probe_providers.py"]
tags: ["openrouter", "models", "configuration", "agent-decided"]
supersedes: ["LLM-0002"]
superseded-by: "LLM-0006"
relates-to: ["LLM-0001", "LLM-0003", "DECIDE-0002"]
confirmation: "cd py && uv run pytest tests/test_catalog.py tests/test_gateway.py"
---

# LLM-0005 — Escape-hatch order and per-path slug resolution

## Context and Problem Statement

Two things changed since LLM-0002. The generative preference order was
re-specified as five models, and generation stopped being on the simulation's
critical path: sim state never depends on generated text, prose is a projection
rendered on demand. Under LLM-0002 every configured slug was fatal at startup,
so a prose model being renamed would stop Jev — the one model the product is
about — from running at all.

Separately, session 1 showed that resolving a slug proves less than it seems:
`typesafe/jev-1.13` resolved perfectly and then 404'd on every call, because the
account's provider allowlist excluded its only provider.

## Considered Options

- **Keep "any unresolved slug is fatal".** Simple, and it was right when prose
  was assumed to be load-bearing. Now it couples the decision path to five
  vendors' naming. Loses.
- **Resolve lazily, per call.** Moves the failure from startup to mid-run, which
  is where LLM-0002 was written to keep it from happening. Loses.
- **Resolve at startup, per path: decisions strict, generation tolerant.** Taken.

## Decision Outcome

Slugs are still resolved against the live catalogue at startup, but per path: an
unknown decision slug is fatal, an unknown generative slug drops out of the
preference list, and only a generative list that resolves to nothing is an error
— raised when prose is requested, not at startup.

The generative order is DeepSeek V4.1 Flash → GLM 5.3 Flash → Gemini 3.8 Flash →
GPT-5.6 Luna → DeepSeek V4 Pro, as `deepseek/deepseek-v4.1-flash`,
`z-ai/glm-5.3-flash`, `google/gemini-3.8-flash`, `openai/gpt-5.6-luna`,
`deepseek/deepseek-v4-pro-0813`. "DeepSeek V4 Pro" is ambiguous in the
catalogue: the undated `deepseek/deepseek-v4-pro` also resolves, to the April
(0423) weights. The dated August build is taken as the one meant; swapping is a
one-line change.

Reachability is checked separately from resolution: `make providers` issues one
tiny real call per model and writes `ops/providers.md`. On 2026-09-20 all six
were reachable, for $0.0005.

### Consequences

- Good: a prose vendor renaming a model cannot stop the simulation.
- Good: reachability is measured, so an allowlist problem costs one command to
  find instead of forty minutes.
- Bad: a typo in a generative slug is now silent until prose is requested, and
  then shows up only as a shorter preference list. `make providers` is the
  check, and it costs money, so it is not part of `make check`.
- Bad: the choice of the 0813 build over the undated slug is my reading of an
  ambiguous name, not something the catalogue settles.
- Reverse it if: generated text becomes an input to simulation state, at which
  point a missing prose model is a correctness problem and must be fatal again.
