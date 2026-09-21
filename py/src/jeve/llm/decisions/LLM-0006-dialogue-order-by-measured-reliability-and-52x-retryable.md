---
id: LLM-0006
title: Dialogue model order by measured reliability, and 52x is retryable
status: accepted
date: 2026-09-20
deciders: ["punitarani", "claude"]
scope: ["py/src/jeve/llm/catalog.py", "py/src/jeve/llm/gateway.py"]
tags: ["openrouter", "models", "retries", "agent-decided"]
supersedes: ["LLM-0005"]
superseded-by: null
relates-to: ["LLM-0001", "LLM-0004", "SIM-0002"]
confirmation: "cd py && uv run pytest tests/test_catalog.py tests/test_gateway.py"
---

# LLM-0006 — Dialogue model order by measured reliability, and 52x is retryable

## Context and Problem Statement

LLM-0005 put `deepseek/deepseek-v4.1-flash` first in the generative order on
price. The audit then measured it (`docs/audit/2026-09-21/README.md` B10): it
failed 8 of 12 billed dialogue attempts, and the attempts that failed were
still paid for, so its effective cost was about seven times GLM's. The order
was a guess; there is now a measurement.

Separately (audit A6.2), a 30-day soak was killed by one HTTP 520. The gateway
retried 429 and 500/502/503/504 and nothing else, so Cloudflare's 52x family —
the edge saying the origin hiccuped — went straight through as a fatal error.

## Considered Options

- **Keep price order, add per-model failure tracking at runtime.** Rejected for
  now: a second mechanism, for a path that is off the simulation's critical
  path and called a few times an hour.
- **Order by measured reliability; cheapest-that-works first.** Taken. The
  order is the owner's, from the B10 numbers.
- **Retry every 5xx.** Rejected: 501 and 505 are not weather, they are bugs in
  the request, and retrying them four times hides that.

## Decision Outcome

The generative order is GLM 5.3 Flash, Gemini 3.8 Flash, GPT-5.6 Luna,
DeepSeek V4 Pro (0813), DeepSeek V4.1 Flash. Per-path resolution from LLM-0005
stands: a decision slug that does not resolve is fatal, a generative slug that
does not resolve is skipped.

520 through 529 join the retryable set. Like any 5xx they may have been billed,
so the failed attempt settles at its reservation and the retry reserves afresh
(LLM-0004 is unchanged: the guard never under-counts).

### Consequences

- Good: a dialogue costs what the cheapest reliable model costs, not seven
  times it.
- Good: an edge hiccup costs one backoff, not a night's run.
- Bad: the order is a snapshot of one afternoon's measurements. Re-measure with
  `make providers` before trusting it after a model release.
- Reverse it if: `ops/providers.md` shows a different reliability order twice
  running.
