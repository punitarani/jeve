---
id: CORE-0002
title: Budget is the independent variable and clock speed is derived from it
status: accepted
date: 2026-09-20
deciders: ["punitarani"]
scope: []
tags: ["cost", "clock", "operations"]
supersedes: []
superseded-by: null
relates-to: ["CORE-0003", "CORE-0004"]
confirmation: null
---

# CORE-0002 — Budget is the independent variable and clock speed is derived from it

## Context and Problem Statement

A simulation meant to run forever has no natural spend limit. Jev is cheap per
call and constant; generation is expensive per call and rare. Left alone, cost
is a function of how busy the world happens to be, and it peaks during an
incident spiral — exactly when the sim is most worth watching.

## Considered Options

- **Fix the clock speed, measure the bill.** Rejected: spend becomes
  uncontrolled and spikes at the worst moment.
- **Run as fast as possible.** Correct for headless validation replicas only.
- **Fix the budget, derive the speed.** Taken.

## Decision Outcome

Model spend has a hard ceiling per real day, and the simulation's clock speed
is whatever that ceiling affords; the unit of cost is the decision point, not
the tick.

Defaults: $2.00 per real day for the live world, ≤ 20 Jev calls per person per
sim-workday, ≤ 4k input tokens per call. Generation is rationed structurally
rather than by price — prose is rendered lazily for viewers, typed escalation
is capped, ontology proposals are weekly.

Jev is 80–90% of spend in every scenario. The design does not depend on Jev
being nearly free for the sim to *exist* — workbench ran a comparable world on
flash LLMs — but it does depend on it for speed above real time, for
statistical validation, and for keeping model calls off the tick barrier.

### Consequences

- Good: an unattended process cannot surprise you with a bill.
- Good: cost per sim-day is an intrinsic number, comparable across runs.
- Bad: speed varies through the day, which the dashboard has to explain.
- Reverse it if: measured cost is so low the governor never binds (delete it,
  keep the cap), or a viewer finds floating speed unreadable.

Long form, with the arithmetic: `docs/design/003-cost-model.md`.
