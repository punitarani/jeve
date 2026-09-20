---
id: WORLD-0001
title: Build and tune the world on rules before wiring in any model
status: accepted
date: 2026-09-20
deciders: ["claude"]
scope: ["py/src/jeve/world/**", "py/src/jeve/decide/policy.py"]
tags: ["world", "testing", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["DECIDE-0001", "CORE-0002"]
confirmation: "cd py && uv run pytest tests/test_world.py"
---

# WORLD-0001 — Build and tune the world on rules before wiring in any model

## Context and Problem Statement

Tuning an economy is fiddly: backlogs must be warm enough to propagate an
outage but not diverge, a cafe must not turn away half its customers, invoices
must actually get paid. Doing that while every iteration costs money and takes
model latency would be slow and expensive, and a defect in the rules would be
indistinguishable from a defect in the model.

## Considered Options

- **Wire the model in from the start**, tune against it. Rejected: every tuning
  iteration costs money and seconds per decision, and the two sources of
  failure are confounded.
- **Rules first, model second, behind one interface.** Taken.

## Decision Outcome

Every agent choice goes through a `Policy`, and `RulesPolicy` — deterministic,
free, no network — is the first implementation; the model swap is a second
implementation of the same protocol, changing nothing upstream.

This is not only a build-order convenience. The rule-based world is null model
N1 from the validation plan: the baseline any later claim about agent cognition
has to beat. Building it first means it exists permanently rather than as
something to be retrofitted when a reviewer asks what the rules alone produce.

It paid for itself immediately. Three defects surfaced in the first end-to-end
run — a scheduler branch that was never reached, a cafe turning away 45% of
customers, an event citing only half its causes — each of which would have been
attributed to the model had the model been in the loop.

### Consequences

- Good: tuning costs nothing, so the fixture was re-run dozens of times.
- Good: a permanent, free baseline for comparison, and a fast test suite.
- Bad: the rules are deliberately crude and will look naive beside a model;
  they are a baseline, not a simulation of a person.
- Bad: two implementations of every decision kind to keep in step.
- Reverse it if: keeping the rules in step with the question sets costs more
  than the baseline is worth.
