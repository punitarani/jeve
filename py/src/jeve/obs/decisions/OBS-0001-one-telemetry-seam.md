---
id: OBS-0001
title: One telemetry seam - OpenTelemetry to Axiom, and nothing at all without a token
status: accepted
date: 2026-09-21
deciders: ["claude"]
scope: ["py/src/jeve/obs/**", "py/src/jeve/sim/daemon.py", "py/src/jeve/api/app.py", "py/src/jeve/llm/gateway.py", "py/src/jeve/llm/ledger.py", "py/pyproject.toml", "fly.toml"]
tags: ["observability", "opentelemetry", "axiom", "layering", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["CORE-0003", "CORE-0008", "SIM-0002", "SIM-0003", "LLM-0004", "LLM-0007", "OPS-0001", "WEB-0005"]
confirmation: "cd py && uv run pytest tests/test_obs.py tests/test_layering.py"
---

# OBS-0001 — One telemetry seam: OpenTelemetry to Axiom, and nothing at all without a token

## Context and Problem Statement

Two processes run forever and nobody can see inside either. SIM-0002's heartbeat
answers "is the world moving", but only while a browser is open and with no
history. Nothing answers why a tick took forty seconds, which call is burning the
budget, or what the daemon was doing before it went `waiting_on_model`. One HTTP
520 ended a thirty-day soak; the diagnosis came from reading stdout afterwards.
`_StreamHub._poll` swallowed every database error, and twenty-odd `print()`
calls were the whole record of a night.

Three constraints shaped the answer. `make check` must pass with no network and
no key. A telemetry failure must not stop a process — the spend checkpoint and
the discrepancy log both had to be made best-effort after a `PermissionError`
crash-looped the sim on boot. And CORE-0003 says sim time comes from the world
clock, while a trace is by definition a wall-clock artefact.

## Considered Options

- **Keep `sim_meta` and stdout.** Rejected: answers "is it up" and nothing else.
- **`axiom-py` and a bespoke shipper.** Rejected: one vendor's client, and a
  trace model we would have to invent and then maintain.
- **`opentelemetry-instrumentation-*`.** Rejected: monkey-patching at import
  time, a second way to produce a span, and no control over `/stream`'s
  nine-hundred-second responses or the poll loop's volume.
- **Logs only, into a drain.** Rejected: no latency distribution, no spend
  series, no link from a slow tick to the call inside it.
- **`opentelemetry-sdk` and the OTLP/HTTP exporter, spans by hand, in a new
  bottom-layer package.** Taken.

## Decision Outcome

Telemetry is one package, `jeve.obs`, at the bottom of the layering beside
`core`, importing nothing from `jeve` but `config`. Nothing outside it names
`opentelemetry`, so Axiom is a backend, not a dependency.

**It is absent when `AXIOM_TOKEN` is unset.** The SDK imports live inside
`start()`, after the token check, so a process with no token never loads
`opentelemetry.sdk`, the exporter, `requests` or `protobuf`: no thread, no
socket. No CI job has a token, so every run exercises that path.

`obs` is not part of `core` on purpose: `core` is the deterministic floor, and a
package owning an exporter thread and a TLS socket does not belong in it. The
layering forbids `obs` importing `core`, so telemetry cannot reach the seeded
clock to time a span with it.

Per-signal configuration is forced, not preferred: Axiom routes logs by
`X-Axiom-Dataset` and metrics by `X-Axiom-Metrics-Dataset`, and `/v1/metrics`
speaks protobuf only, so one shared `OTEL_EXPORTER_OTLP_HEADERS` cannot say it.

Sim time never becomes a timestamp. No jeve module passes a `start_time`; the
SDK stamps spans inside site-packages. Sim time rides as `jeve.sim_time` and
`jeve.sim_label`, and a test asserts a span's `start_time` is of nanosecond
order, so a sim-second leaking into a timestamp fails the build. Prompt and
completion text are never recorded (GEN-0001). `start()` cannot raise.

This is a second egress path where LLM-0004 says there is one. LLM-0004 is about
reaching a *model*: it is enforced by the `httpx` ban outside `jeve.llm` and a
CI grep for OpenRouter URLs, both still holding since the exporter rides
`requests`. Telemetry carries no prompt, resolves no model, spends nothing.

### Consequences

- Good: tick latency, call cost, query duration and daemon status are one query
  away with history; the off path is tested every commit, not merely asserted.
- Bad: nine transitive dependencies against `py/AGENTS.md`'s stdlib-first
  standard — the largest such addition here, and a deliberate trade, not a
  habit. A hand-rolled exporter is a protocol you own; OTLP is a spec you don't.
  On Alpine `protobuf` falls back to pure Python for want of a musllinux wheel;
  at a few spans a second that is irrelevant, and the escape is `-slim`.
- Bad: ingest volume is now an operating cost. Hence `_StreamHub._poll` is
  metrics-only, and `http.route` is recorded instead of `url.path`. Reverse this
  if the bill nears the model budget, or the exporter ever stalls a tick.
