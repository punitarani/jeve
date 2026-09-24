---
id: "DECIDE-0005"
title: "Tier 1 runs in shadow inside the tick, and a set goes live by name"
status: "accepted"
date: 2026-09-24
deciders: ["claude"]
scope: ["py/src/jeve/decide/escalation.py", "py/src/jeve/decide/jev_policy.py", "py/src/jeve/decide/policy.py", "py/src/jeve/decide/recorder.py", "py/src/jeve/sim/escalations.py", "py/src/jeve/sim/panel.py", "py/src/jeve/gen/ontology.py", "py/migrations/0013_escalations.sql", "py/tests/test_escalation.py", "py/tests/test_measurement.py"]
tags: ["escalation", "confidence", "llm", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["DECIDE-0002", "DECIDE-0004", "LLM-0006", "SIM-0002", "CORE-0004"]
confirmation: "cd py && uv run pytest tests/test_escalation.py tests/test_measurement.py"
---

# DECIDE-0005 — Tier 1 runs in shadow inside the tick, and a set goes live by name

## Context and Problem Statement

DECIDE-0002 said an uncertain high-stakes answer is asked again of a flash LLM,
in the same typed shape, and left three things open: whether the second
opinion waits for the tick or lands later, how it is cached and replayed, and
who decides that the world may act on it. design/005 wanted it asynchronous,
with a hesitation of up to three ticks.

## Considered Options

- **Synchronous, inside the batch, off by default and shadow first.** Taken.
- **Asynchronous, a `deliberating` state landing next tick.** Rejected for
  now: a third thing a person can be doing, plus a scheduler hook, to save
  latency nobody has measured. The report measures it (below).
- **Straight to live on the placeholder bands.** Rejected: agreement is the
  only evidence there is, and it has to be collected before it is acted on.

## Decision Outcome

Tier 1 is asked inside `JevPolicy.decide_many`, between Jev's answer and the
draw, off unless `JEVE_ESCALATION` says `shadow` or `live`; it acts only for
sets named in `JEVE_ESCALATION_LIVE`.

- **The rule** is design/005's per primitive, with stakes per set in
  `escalation.STAKES`; propensities escalate only at high stakes. A 2% sample
  keyed by `(person, decision_seq, kind)` escalates confident answers too.
- **Room** is 5% of yesterday's decisions (floor 25), from committed rows,
  less what this tick has used, taken in the order asked: a batch decides as
  its decisions one at a time would. `Policy.begin_tick` resets the tick's
  count, so a retried tick decides as its replay does. Live answers have a
  room of their own, counted from live rows, which shadow cannot move.
- **Cache and replay.** The request is `escalation.request_for`: Jev's state
  and questions, a strict schema of a probability per option, seed 0, stored
  as kind `tier1` under everything sent. Every model is looked up before any
  is called, and one whose reply is on record, readable or not, is not asked
  again. A shadow failure leaves a marker beside the key, so it is not paid
  for twice; an unresolvable model is marked for everyone.
- **Shadow is measurement.** `explore` purpose, 45 seconds a tick in all, and
  any failure or replay miss means no row. It never stops the world.
- **Live is a decision**, and only for an answer Jev was unsure of: the 2%
  sample stays shadow. `gate` purpose; a judgement takes the LLM's answer, a
  propensity samples an even mixture, and `decisions.source` is `llm`. A
  failure raises and the tick waits (SIM-0002, CORE-0004); a replay miss is a
  `ReplayMissError`. If every model's reply is on record and unreadable, Jev's
  answer stands, the same way on every retry and replay.
- Every escalation is a row in `escalations` beside its decision.
  `make escalation-report`, `make judge-panel` and `make ontology-gaps` read
  what was kept.

### Consequences

- Good: nothing about the world changes until a person names a set, and the
  evidence for naming it accumulates from the first shadow day.
- Bad: shadow can slow a tick by up to 45 seconds, and a model that failed a
  shadow question once is not asked it again. A consequence class for two
  equivalent options (design/005) is not implemented: no escalatable choice
  has two options with the same consequence today.
- Reverse it if: the report's p95 latency matters to pacing (build the
  `deliberating` state), or agreement inside the bands exceeds 95% for every
  set (delete tier 1 and keep the logging).
