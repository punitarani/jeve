---
id: LLM-0002
title: Resolve model slugs against the live catalogue and fail loudly
status: accepted
date: 2026-09-20
deciders: ["punitarani"]
scope: ["py/src/jeve/llm/catalog.py"]
tags: ["openrouter", "models", "configuration"]
supersedes: []
superseded-by: null
relates-to: ["LLM-0001", "DECIDE-0002"]
confirmation: "cd py && uv run pytest tests/test_catalog.py"
---

# LLM-0002 — Resolve model slugs against the live catalogue and fail loudly

## Context and Problem Statement

A wrong model slug is the quiet failure in this kind of build: the request is
accepted, something answers, and the run measures a model nobody chose. Model
names given from memory are unreliable — of four supplied for this project, one
("Qwen 3.8 Next Flash") does not exist at all, and the real article had the
worst latency tail of the candidates.

## Considered Options

- **Hard-code the slugs.** One rename and the run is silently wrong.
- **Fall back to a default when a slug is unknown.** The same failure, automated.
- **Resolve at startup against `/models`, and refuse to start otherwise.** Taken.

## Decision Outcome

Every configured slug is resolved against OpenRouter's live catalogue before
any call, and an unresolved name is fatal with near-matches printed.

Two listings are required, because decision models do not appear in the default
`/models` response at all — Jev is visible only under
`?output_modalities=decisions`. Resolution also yields per-token prices, which
is what lets the ledger price a response that omits its cost (LLM-0004).

The preference order is GLM 5.3 Flash → DeepSeek V4.1 Flash → GPT-5.6 Luna for
generation, `typesafe/jev-1.13` for decisions, with Qwen dropped. Verified
slugs: `z-ai/glm-5.3-flash`, `deepseek/deepseek-v4.1-flash`,
`openai/gpt-5.6-luna`, `typesafe/jev-1.13`.

### Consequences

- Good: a rename is a startup crash with a near-match list, not a silent swap.
- Good: prices come from the catalogue, so they cannot drift from a constant.
- Bad: startup needs the network even for work that would not otherwise call a
  model — so replay runs skip the resolver entirely.
- Reverse it if: the catalogue becomes unreliable enough to block startup.
