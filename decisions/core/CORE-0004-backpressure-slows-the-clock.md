---
id: CORE-0004
title: Slow the clock under backpressure; never default a decision
status: accepted
date: 2026-09-20
deciders: ["punitarani"]
scope: ["py/src/jeve/llm/**"]
tags: ["backpressure", "reliability", "clock"]
supersedes: []
superseded-by: null
relates-to: ["CORE-0002", "CORE-0003"]
confirmation: null
---

# CORE-0004 — Slow the clock under backpressure; never default a decision

## Context and Problem Statement

Model latency is not under our control. When a tick's decisions are slower than
its budget, something has to give: the world's pace, the decision's quality, or
its timeliness.

## Considered Options

- **Degrade** — substitute a default when the model is late. Rejected: it
  converts infrastructure weather into behaviour. A brownout becomes a wave of
  idling that then trips the degeneracy detectors and enters the permanent
  record as something the agents did. workbench has the cautionary tale — an
  engine error leaked into agent memory and a firm built a shared story about
  an outage that never happened.
- **Queue** — apply late decisions later. Rejected: a decision about the world
  at T applied at T+3 is wrong with a correct timestamp, and an unbounded queue
  in a forever-process is a memory leak.
- **Slow the clock.** Taken.

## Decision Outcome

The tick is a barrier: sim time does not advance until every decision due at
that tick has a real answer, so a slow model means a slow world and a dead
model means a paused world.

This is nearly free because the world runs on its own clock (CORE-0003) —
nobody inside it can tell. No LLM call is ever on the barrier, since end-to-end
latency runs to 40–220s at P99: typed escalation and prose rendering are
asynchronous jobs. A decision awaiting escalation makes its agent *hesitate*
for up to three ticks, which is behaviour, not an artefact.

### Consequences

- Good: no fabricated decision ever enters the record.
- Bad: under provider trouble the dashboard stutters or stops. It says why.
- Bad: sim availability is bounded by decision-model availability.
- Reverse it if: the world spends more than 5% of wall time waiting, with a
  standby provider configured.

Long form: `docs/design/002-backpressure.md`.
