---
id: LLM-0008
title: trace every model call to braintrust, from one module, off by default
status: superseded
date: 2026-09-21
deciders: ["claude"]
scope: ["py/src/jeve/tracing.py", "py/src/jeve/llm/gateway.py", "py/src/jeve/decide/jev_policy.py", "py/src/jeve/api/app.py", "py/tests/test_tracing.py"]
tags: ["observability", "braintrust", "llm", "agent-decided"]
supersedes: []
superseded-by: LLM-0009
relates-to: ["LLM-0001", "LLM-0004", "LLM-0007", "DECIDE-0004", "CORE-0005"]
confirmation: "cd py && uv run pytest tests/test_tracing.py"
---

# LLM-0008 — trace every model call to braintrust, from one module, off by default

## Context and Problem Statement

We could say what a call cost and not what it was. `spend_entries` prices every
call and `model_calls` keeps the bytes, but reading either means SQL against a
production database, so nobody did. A slow tick, a question set that started
answering badly after a wording change, a provider quietly worse than the one
before it — invisible unless you already suspected it. The research question is
whether typed decisions can replace a generated-text agent loop, and that is a
question about what the model *said*, not only what it charged.

Wanting traces was not contested. Three things were: where a tracing dependency
may live in a codebase whose one network rule is "only `jeve.llm` talks to
anything"; whether tracing may ever change a run; and what happens when the
tracer itself is broken.

## Considered Options

- **The `braintrust` SDK behind one guarded module** — it batches, retries and
  flushes; we write span shapes and nothing else.
- **OpenTelemetry to Braintrust's OTLP endpoint** — loses: more dependencies
  than the SDK, and its conventions have no shape for a typed decision, so the
  noul/choice/score answers become opaque strings.
- **Hand-rolled POSTs to Braintrust's ingest API** — loses: no new dependency,
  but it reimplements batching, retry and span identity against an API we do
  not own. That code keeps working until the day it silently stops.
- **Nothing, and better SQL over `model_calls`** — loses: the data has been
  there and unread for the life of the project. The missing thing is a place to
  look, not a place to store.

## Decision Outcome

Model calls are traced to Braintrust from a single guarded module,
`jeve.tracing`, which is a no-op unless `BRAINTRUST_API_KEY` is set.

Spans are built by hand: the gateway posts raw `httpx`, so `wrap_openai` and
friends have nothing to patch (`wrap_openrouter` patches the official
`openrouter` package, which this project does not use). A batch of decisions is
the root, each distinct request is an `llm` span under it, and each HTTP try is
a span under that — retries stay visible without counting cost four times. A
cache hit never reaches the gateway, so hits are counted on the batch span;
`live_calls` is the number that matters and a span per hit would bury it. Cost
is logged as `metrics.estimated_cost` from OpenRouter's own `usage.cost`:
Braintrust would otherwise price the span from a registry that has never heard
of `typesafe/jev-1.13`, and a trace that disagrees with the ledger is worse
than no trace.

`jeve.tracing` is a module beside `config.py` and `db.py`, not a package — it
cuts across the layering rather than sitting in it. The layering is unchanged.

One thing needed care. `JevPolicy._Bridge` runs the gateway on its own loop on
its own thread, and `run_coroutine_threadsafe` copies the context over *there*,
so the ambient current span never crosses. The batch span's handle is exported
on the engine thread and passed down explicitly.

### Consequences

- Good: a call's prompt, typed answers, provider, tokens and real dollar cost
  are one click apart, and a batch shows its own cache hit rate.
- Good: off is the default — no key, no import, no socket. The key is the only
  switch, so nothing can disagree with it about whether tracing is on.
- Bad: `braintrust` pulls ten transitive dependencies into a project whose
  runtime list was five and whose standard is stdlib-first. `tqdm` in a daemon
  is silly. That is the price of not owning a wire protocol.
- Bad: `jeve.tracing` opens a socket from outside `jeve.llm`. LLM-0004 governs
  paths to a *model* and to *spend*, and this is neither — but it is the first
  exception, and it is safe only because no tracing failure reaches a caller.
- What would reverse it: a tracing failure that reaches a tick. The module
  catches everything, warns once, and latches off — the rule
  `gateway._log_discrepancy` was written for after an unwritable ops dir killed
  a decision call on Fly. If a span halts the world anyway, the span goes.
