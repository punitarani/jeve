---
id: CORE-0012
title: Errors, traces, metrics and logs go to Sentry from one guarded module; the DSN is the only switch
status: accepted
date: 2026-09-22
deciders: ["claude"]
scope: ["py/src/jeve/telemetry.py", "py/src/jeve/sim/daemon.py", "py/src/jeve/api/app.py", "py/src/jeve/llm/gateway.py", "py/src/jeve/decide/jev_policy.py", "py/scripts/sentry_probe.py", "py/tests/test_telemetry.py", "apps/web/next.config.ts", "apps/web/src/instrumentation-client.ts", "apps/web/src/app/global-error.tsx", "apps/web/src/lib/api.ts"]
tags: ["observability", "sentry", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["LLM-0008", "SIM-0002", "SIM-0003", "OPS-0001", "WEB-0005"]
confirmation: "cd py && uv run pytest tests/test_telemetry.py"
---

# CORE-0012 — Errors, traces, metrics and logs go to Sentry from one guarded module; the DSN is the only switch

## Context and Problem Statement

Two processes run for ever and a static site fronts them, and nothing outside a browser tab can see inside any of them. The heartbeat answers "is the world moving" only while a page is open. Nothing answered why a tick took forty seconds, which call was burning the budget, or what the daemon was doing before it went `waiting_on_model`; one HTTP 520 ended a thirty-day soak and the diagnosis came from stdout afterwards; a Braintrust key sat in Doppler and never reached Fly for an hour; the stream hub swallowed every database error, so a wedged pool read as an idle world. LLM-0008 carries what the model *said* and nothing else.

Contested: a second observability backend beside Braintrust; one Sentry project or three; how a span reaches the gateway's thread; what tracing `/health` and `/stream` would cost; whether the daemon's prints become logs; whether a static export gets a server-side SDK; and whether source maps may ever reach the CDN.

## Considered Options

- **The Sentry SDKs behind one guarded Python module and one client init file** — taken.
- **OpenTelemetry to Axiom** (PR #6) — loses: nine transitive dependencies for a wire protocol we would then own the shape of, and no error grouping; issues are the thing an operator opens first.
- **Extend Braintrust** — loses: it has no issues, metrics or logs. It answers "what did the model say", which is a different question from "is the system alive".
- **Stdlib `logging` to `fly logs` only** — loses: no grouping, no traces, no alerting; that is where we already were.

## Decision Outcome

Errors, traces, metrics and structured logs go to Sentry through `jeve.telemetry`, a second guarded module beside `jeve.tracing`, with three projects (api, sim, web), the DSN as the only switch, and no telemetry failure able to reach a tick or a request.

Two backends stay because they answer different questions: Braintrust holds the prompt and the typed answers; Sentry holds what it cost the system — status, latency, retries, spend, and the halt with its exit code. The Python module mirrors LLM-0008's three properties (no DSN, no import, no socket; never fatal, one warning then latched off; a pure side effect — no header is added to a request whose bytes are a cache key). A DSN per service (`SENTRY_DSN_API`, `SENTRY_DSN_SIM`, `SENTRY_DSN` as the fallback) because `api` and `sim` share one Fly app and one `[env]`, and the alternative was wrapping the process commands in `sh -c` in front of the entrypoint's signal handling.

Tracing runs in stream mode: the daemon runs for days, its calls cross `JevPolicy._Bridge`'s thread (the tick span is passed as a handle, exactly as the Braintrust one is), and a crash must not lose the tick in flight. `/health` (Fly's probe, every ten seconds) and `/stream` (a 900-second body) are dropped by name. Prints stay: they are the human stream and the tests assert on them; `_status`, the one funnel every state change passes through, is where the structured record is made. Weather (SIM-0002) is a count and a warning, never an issue. The site gets only the client SDK — a static export has no server — and source maps exist only in a build that holds an upload token; the deploy scrubs `out/` regardless.

### Consequences

- Good: a halt is an issue with its exit code; a tick has a duration and the calls under it; a 5xx has a trace; the browser's `/state` fetch and the API's handling of it are one trace.
- Bad: `sentry-sdk` and its transitive set in a stdlib-first project, and a second observability dependency to keep current; cross-origin fetches are preflighted once a DSN is set.
- What would reverse it: a telemetry failure that reaches a tick (the rule LLM-0008 was written under), or the two backends drifting into answering the same question — then one goes.
