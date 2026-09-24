---
id: "WORLD-0011"
title: "Route an escalation through whoever was cornered"
status: "accepted"
date: 2026-09-24
deciders: ["claude"]
scope: ["py/src/jeve/world/episodes.py", "py/src/jeve/world/engine.py", "py/tests/test_loops.py"]
tags: ["escalation", "encounters", "support", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["WORLD-0008", "WORLD-0007", "WORLD-0010"]
confirmation: "cd py && uv run pytest tests/test_loops.py"
---

# WORLD-0011 — Route an escalation through whoever was cornered

## Context and Problem Statement

The field report found escalation social rather than procedural: an outage was
escalated by whoever from the software company happened to be in the cafe,
and every one of them — a support agent, the account manager — shortened it on
the spot. Triage severity had no consequence at all, and a customer's only way
to reach the vendor was to be standing next to one.

## Considered Options

- **Keep one rule: anyone at the vendor escalates.** The finding. Loses.
- **Only engineers can escalate.** Makes cornering support worthless, which is
  as wrong as making it decisive. Loses.
- **Engineers act at once; anyone else decides whether to pass it on.** Taken.

## Decision Outcome

A complaint raised with an engineer (the founder, an engineering lead, an
engineer or an SRE) shortens the outage at once, as before; raised with anyone
else, it becomes an `escalation.handoff` decision a quarter of an hour later —
relay it to engineering, or leave it in the queue. Support escalates by rule
once three blocked customers' tickets are triaged against one outage, and a
customer can ring their account manager as a workaround (WORLD-0010).

Procedure is weaker than a face. A relay by phone, or support's rule, puts the
incident at the top of the queue: what is left of it halves, once per
incident. Only an engineer, or a relay made in person, escalates it: what is
left quarters, once. Either can follow the other, so space still matters.

### Consequences

- Good: escalation latency depends on whom a customer reached, and triage
  severity reaches the outage.
- Good: the phone reaches the vendor from anywhere, not only the cafe.
- Bad: episodes and one-shot encounters that press a support agent no longer
  guarantee an escalation, so WORLD-0007's docking gap must be re-measured.
- Reverse it if: handoffs are relayed almost always under Jev, which would make
  the extra decision a quarter-hour delay and nothing else.
