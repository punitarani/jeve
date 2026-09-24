---
id: "API-0004"
title: "Degeneracy detectors are part of the field report, and each is seen to fire"
status: "accepted"
date: 2026-09-24
deciders: ["claude"]
scope: ["py/src/jeve/api/detectors.py", "py/src/jeve/api/report.py", "py/src/jeve/api/contracts.py", "py/tests/test_detectors.py", "apps/web/src/components/report/LiveReport.tsx"]
tags: ["api", "reports", "measurement", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["API-0003", "DECIDE-0005", "WORLD-0011"]
confirmation: "cd py && uv run pytest tests/test_detectors.py"
---

# API-0004 — Degeneracy detectors are part of the field report, and each is seen to fire

## Context and Problem Statement

The golden field report found a world that ran and balanced its books but had
settled into ruts nobody was watching for: no bill was ever disputed, support
chatted in the cafe with a backlog, a choice kept coming out the same, and a
person's temperament said more than their situation. Each was found by a
person reading queries once. A rut that returns after a change would go unseen
until someone read them again.

## Considered Options

- **Detectors in `GET /report`, over the last seven sim-days.** Taken.
- **Soak invariants only.** Rejected: the soak runs rules on its own database;
  the ruts that matter are the model's, in the world people look at.
- **A separate `/health` endpoint.** Rejected: a second memoised aggregate for
  numbers the report already half computes (API-0003).

## Decision Outcome

`FieldReport.detectors` carries eight readings from `jeve.api.detectors`, each
with a value, the line past which it fires, and the rows it came from; the live
report shows them first.

They are idle-with-backlog (sampled from where support *is* at half past each
working hour, not from decisions, which since WORLD-0009 are mostly
lunchtimes), collapsed acts, role information, friction per week, money
velocity, persona signal (a two-proportion z of at least 2 on some trait, not a
gap size, which chance alone exceeds), ontology gaps and a redundant tier 1.

`tests/test_detectors.py` builds one healthy rules world, asserts nothing
fires, then breaks it once per detector inside a rolled-back transaction and
asserts that detector fires. A detector without such a test is not added.

### Consequences

- Good: a regression into a rut shows on the page the next tick.
- Bad: every report now scans a week of decisions and moves; memoised per
  tick, it costs one scan a tick.
- Reverse it if: a detector fires on healthy runs often enough that people stop
  reading the section. Fix the line or delete the detector, never mute it.
