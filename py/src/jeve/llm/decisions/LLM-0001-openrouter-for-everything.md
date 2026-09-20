---
id: LLM-0001
title: Reach every model through OpenRouter, including Jev
status: accepted
date: 2026-09-20
deciders: ["punitarani"]
scope: ["py/src/jeve/llm/gateway.py", "py/src/jeve/llm/catalog.py"]
tags: ["openrouter", "jev", "routing"]
supersedes: []
superseded-by: null
relates-to: ["LLM-0003", "LLM-0004"]
confirmation: "cd py && uv run pytest tests/test_gateway.py"
---

# LLM-0001 — Reach every model through OpenRouter, including Jev

## Context and Problem Statement

Typed decisions come from TypeSafe's Jev, which has a native API at
`api.typesafe.ai/v1/systemone`. Earlier research recommended targeting it
directly: lower latency on the critical path, twice the context (64k vs 32k),
documented rate limits, and a stable `v1` rather than an `/alpha/` path.

## Considered Options

- **Native TypeSafe for decisions, OpenRouter for generation.** Two vendors,
  two keys, two spend meters, two failure domains.
- **OpenRouter for everything.** Taken, as a standing constraint.

## Decision Outcome

Everything goes through OpenRouter: chat completions at `/api/v1/chat/completions`
and Jev at `/api/alpha/decisions`, under one key with one spend meter.

One meter is the real argument. The ceiling in LLM-0004 is only enforceable
because `GET /api/v1/key` reports every dollar this project spends; a second
vendor would need a second reconciliation path and would make the ceiling
approximate. The cost is a real hop of latency, half the context, and an alpha
path that may change under us — accepted, because nothing in this build is
latency-bound yet.

An implementation trap worth recording: the Decisions endpoint is a *sibling*
of `/api/v1`, not a child. A client whose base URL is `.../api/v1` and which
posts a relative `/api/alpha/decisions` produces `/api/v1/api/alpha/decisions`
and a bare 404 that reads like the endpoint not existing.

### Consequences

- Good: one key, one meter, one ledger, one place to reconcile.
- Bad: Jev's context is 32k here against 64k native, so state must stay small.
- Bad: an `/alpha/` path carries no compatibility promise.
- Reverse it if: decisions land on the tick's critical path and the extra hop
  shows up in the tick budget, or the alpha endpoint breaks under us.

Long form on the native/OpenRouter comparison:
`docs/research/00-ground-truth.md` §2.
