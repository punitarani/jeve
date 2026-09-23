---
id: "LLM-0009"
title: "one trace per tick, and each batch carries its decisions"
status: "accepted"
date: 2026-09-23
deciders: ["punitarani", "claude"]
scope: ["py/src/jeve/tracing.py", "py/src/jeve/world/engine.py", "py/src/jeve/decide/jev_policy.py", "py/src/jeve/llm/gateway.py", "py/src/jeve/api/app.py", "py/src/jeve/sim/daemon.py", "py/tests/test_tracing.py", "py/tests/test_jev_policy.py"]
tags: ["observability", "braintrust", "llm", "agent-decided"]
supersedes: ["LLM-0008"]
superseded-by: null
relates-to: ["LLM-0004", "LLM-0007", "DECIDE-0004", "SIM-0002"]
confirmation: "cd py && uv run pytest tests/test_tracing.py tests/test_jev_policy.py"
---

# LLM-0009 — one trace per tick, and each batch carries its decisions

## Context and Problem Statement

LLM-0008 made a decision batch the root of a trace and logged only counters
on it. In production that was about 720 traces an hour, each a 10ms
`decide.batch` with input null, no output, and no children: nearly every batch
is answered from the call cache or settled by a gate, so it never reaches the
gateway, and the counters sit in metadata that Braintrust's table does not
show. The SDK was never the problem. Run in memory, it nested batch → call →
try across the gateway thread exactly as intended. What we logged, and where
the root sat, made every trace look empty.

## Considered Options

- **A tick is the root; each batch lists its decisions** — taken.
- **Keep the batch as the root, with input and output** — three traces a tick,
  most of them cache lookups, with nothing tying them to the moment.
- **Trace only batches that call the model** — cache-served decisions vanish
  from the one place you would look to see what the model said.
- **OpenTelemetry, or hand-rolled ingest** — rejected in LLM-0008 for reasons
  that still hold. The SDK works; the shape was wrong.

## Decision Outcome

Every sim tick is one Braintrust trace, from a single guarded module
(`jeve.tracing`) that is a no-op unless `BRAINTRUST_API_KEY` is set. Each
decision batch under the tick logs every decision's facts as input and, as
output, what was chosen and whether it was gated, cached or live. Live model
calls and their HTTP tries nest beneath.

`Engine.tick` opens `sim.tick`, whose input is the clock and whose output is
what the tick did. `JevPolicy.decide_many` opens `decide <kind>` with one input
row per context (person, role, kind, facts, traits) and one output row per
decision (chosen, distributions, draws, PRNG path, model call). A mixed batch
is `decide.batch`, so the name set stays bounded by the question sets. A cache
hit is still a row, never a span. Each distinct live request is an `llm` span,
and each HTTP try a `function` span under it. Cost appears only as
`metrics.estimated_cost` (OpenRouter's own number) on `llm` spans, so nothing
is counted twice. The batch's handle still crosses `JevPolicy._Bridge`
explicitly, because contexts do not.

What LLM-0008 got right stands. The key is the only switch. Every SDK call is
guarded, and the first failure warns once and latches tracing off: no span may
halt a tick. Spans read what was sent and never rebuild it (DECIDE-0004).

### Consequences

- Good: every root has an input and an output, and what the model said is
  readable for every decision, including those served from the cache.
- Good: a tick that fails carries its error on its own trace, and the retry
  (SIM-0002) is the next one.
- Bad: ingest per tick grows from about 2KB to, measured on a replayed day,
  about 30KB on average and 58KB at most (1.3MB per sim-day); three
  quarters of it is the `agent.tick` batch. If that costs too much, list
  distributions once per model call before cutting detail.
- Bad: `jeve.world` now imports `jeve.tracing`, and rules runs trace too when
  the key is set (`metadata.policy` tells them apart).
- What would reverse it: a tracing failure that reaches a tick, or an ingest
  bill that outweighs reading the traces.
