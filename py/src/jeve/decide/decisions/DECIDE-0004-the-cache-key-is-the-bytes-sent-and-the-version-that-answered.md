---
id: DECIDE-0004
title: The cache key is the bytes that were sent and the model version that answered
status: accepted
date: 2026-09-20
deciders: ["claude"]
scope: ["py/src/jeve/llm/protocol.py", "py/src/jeve/llm/gateway.py", "py/src/jeve/llm/catalog.py", "py/src/jeve/decide/jev_policy.py", "py/src/jeve/decide/recorder.py", "py/fixtures/cassettes/**"]
tags: ["cache", "replay", "determinism", "agent-decided"]
supersedes: ["DECIDE-0003"]
superseded-by: null
relates-to: ["WORLD-0001", "LLM-0004", "SIM-0002"]
confirmation: "cd py && uv run pytest tests/test_jev_policy.py tests/test_gateway.py"
---

# DECIDE-0004 — The cache key is the bytes that were sent and the model version that answered

## Context and Problem Statement

DECIDE-0003 keyed the call cache by a hash of the request's *canonical* JSON:
keys sorted, model slug as configured. The audit
(`docs/audit/2026-09-21/README.md` A8) showed what that hides. Reversing the
order of every question's options changes 1,741 of 1,787 wire bodies, and all
1,787 rows still hit: option order is part of what Jev is asked (it answers in
its own order, and sampling walks the *declared* one), and the key cannot see
it. The slug is undated, `typesafe/jev-1.13`, while every recorded row was
answered by `typesafe/jev-1.13-20260917`; a new build behind the same slug
would be served from the old build's answers and `make e2e` would stay green on
decisions Jev no longer makes.

The request body was also built in three places — the gateway, the policy, and
the policy's hashing helper — agreeing by convention.

## Considered Options

- **Keep canonical JSON, add the option order as a field.** Rejected: a second
  description of the request that must be kept in step with the first.
- **Hash the bytes.** Taken. What is sent is what is keyed, by construction.
- **Send the dated slug.** Rejected for now: unverified that the Decisions
  endpoint accepts it, and it would not detect a silent re-point anyway. The
  response says which build answered; that is the ground truth.
- **On a version change, treat it as a miss and re-record quietly.** Rejected:
  with first-writer-wins storage it is a loop that pays for every call on every
  run and never hits, and it changes the world's behaviour without anyone
  deciding to.

## Decision Outcome

`DecisionRequest.wire_bytes()` is the one place a decision body is built. The
gateway posts exactly those bytes; the policy hashes exactly those bytes.

The key is `H("v2" | version | wire_bytes)`. A lookup uses the **pin**, the
dated build the repo was recorded against (`DECISION_PIN` in `llm/catalog.py`).
A response is stored under the version that **served** it. When those differ
the response is kept — it was paid for — and the policy raises
`ModelVersionDriftError`, which is not weather (SIM-0002): the daemon halts and
says so. Moving the pin is an explicit act, followed by `LIVE=1 make e2e` and a
committed cassette.

The wire body is stored as text beside the row (`model_calls.wire`), because
JSONB and a sorted cassette both forget order, and order is now the point.

### Consequences

- Good: reordering options, rewording a question, or a new model build are all
  misses. A test pins those three and the hit.
- Good: one builder for the body; the three-way agreement is gone.
- Bad: every existing cassette row is orphaned by the new key. The whole golden
  run is re-recorded once (about four cents).
- Bad: a model release halts a recording world until somebody moves the pin.
  That is the intent: it is a decision about the experiment, not an outage.
- Reverse it if: TypeSafe publishes dated slugs that can be requested directly,
  at which point the pin moves into the request and the check becomes a
  formality.
