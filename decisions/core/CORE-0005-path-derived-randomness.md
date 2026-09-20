---
id: CORE-0005
title: Replay from the recorded log, and derive every random draw from a path
status: accepted
date: 2026-09-20
deciders: ["punitarani"]
scope: []
tags: ["determinism", "replay", "seeding"]
supersedes: []
superseded-by: null
relates-to: ["CORE-0007"]
confirmation: null
---

# CORE-0005 — Replay from the recorded log, and derive every random draw from a path

## Context and Problem Statement

Jev exposes no seed and no temperature and documents no determinism guarantee;
its own published repeat runs show argmax flips. So a run cannot be reproduced
by re-asking. But a simulation nobody can replay cannot be debugged, and an
intervention study needs two branches that differ only by the intervention.

## Considered Options

- **Chase bit-exact reproduction from the seed** by pinning providers and
  caching. Rejected: fails on the first novel context and buys false comfort.
- **Stateful RNG streams, checkpointed.** Rejected: a class of resume bugs.
  Concordia does not restore RNG state at all.
- **Argmax everywhere, so nothing is random.** Rejected: deterministic given
  state, and therefore a machine for loops and absorbing idle states.
- **Record responses; derive draws from paths.** Taken.

## Decision Outcome

A recorded run replays to a byte-identical event log from its stored model
responses, never by re-querying; every random draw is a pure function of a path
(`seed, agent, decision_seq, question`), so no RNG state exists to persist.

Every model call is stored under a content hash of (provider, resolved model
version, request). That one record serves four purposes: a re-executed tick
after a crash finds its answers instead of paying twice; replay raises on a
miss; control and treatment branches share answers for contexts the
intervention did not touch; and threshold tuning reads it offline.

Keying draws by decision sequence rather than tick means a scheduler change
does not reshuffle every agent's luck — which is also what makes common random
numbers work across fork branches.

### Consequences

- Good: `kill -9` cannot desynchronise randomness, because there is none to lose.
- Good: a code-version change is recorded as an event rather than refused.
  workbench refuses to resume on a fingerprint change and a `ruff format` once
  broke a live run; that is right for a frozen recording, fatal for a forever one.
- Bad: replay across a version seam means checking out each segment's sha.
- Reverse it if: Jev turns out to be deterministic for identical requests —
  nothing changes architecturally, but studies get cheaper.

Long form: `docs/design/007-determinism.md`.
