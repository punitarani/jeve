---
id: "WORLD-0006"
title: "Give a meeting with a stake rounds instead of one shot"
status: "accepted"
date: 2026-09-22
deciders: ["claude"]
scope: ["py/src/jeve/world/episodes.py", "py/src/jeve/world/space.py", "py/migrations/0009_episodes.sql", "py/tests/test_episodes.py", "py/src/jeve/sim/episode_study.py"]
tags: ["episodes", "encounters", "space", "causality", "resolution", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["WORLD-0003", "WORLD-0005", "MEM-0002", "DECIDE-0001", "CORE-0004", "CORE-0009"]
confirmation: "cd py && uv run pytest tests/test_episodes.py"
---

# WORLD-0006 — Give a meeting with a stake rounds instead of one shot

## Context and Problem Statement

WORLD-0003's encounter is one question about the present moment with one
consequence. A conversation therefore cannot develop — nothing carries from one
moment of it to the next — and has nowhere to put a result, since escalation is
the only thing a meeting may change. So the project could not ask whether more
resolution inside an encounter produces a better world. The prior-art survey
(`docs/research/03-recursive-micro-simulation.md`) found nobody else has either,
and that the nearest evidence is *negative*: monologue agents reach the same
stance distribution as full debates. Building this as a feature would be a bet
against the only evidence there is.

## Considered Options

- **Leave the encounter alone.** Free, and leaves the one measurement the survey
  says is missing unmeasurable.
- **Give every encounter rounds.** Multiplies the most expensive question set in
  the world by the round count to refine meetings where nothing is at stake.
- **Replace the one-shot entirely.** Then there is no control arm, and a
  resolution effect cannot be told from a base-rate change.
- **Rounds only where there is a stake, the one-shot kept as the control, and the
  difference measured.** Taken.

## Decision Outcome

A meeting becomes an **episode** — two to four people, up to three rounds, one
typed request per participant per round — only when they have something between
them: a broken module one can act on, a live bill between their firms, or news
one holds and another lacks. Everyone else keeps the one-shot encounter, which
stays the control arm and the cheap proxy. Episodes are **off by default**.

Rounds are sequential; questions inside a round are not, because Jev answers a
request's questions independently. So everyone reads the state as it stood at the
start of the round and their acts are folded in seat order — influences, then one
reaction — and nothing is written to the world until the episode closes, which is
what keeps it atomic to the tick that spawned it. A pair resolved as an episode is
never also resolved as an encounter: `episodes.run` returns the pairs it consumed.
Every role can leave, so `settled` / `emptied` / `rounds` all occur and the cap is
a backstop. Depth is capped at one in code and in the schema. Three rounds is most
of a quarter of an hour, so a participant does not also clear tickets that tick.

What folds back is typed and reaches money by paths the tests already walk: `press`
shortens an outage; `mention` moves a fact, and hearing your software is down
brings your notice forward, so word of mouth reaches a ticket; `promise` records a
commitment that raises the pressure on the next payment decision (MEM-0002). Money
is still moved only by code. Escalation moved into this module and is reached from
either resolution, so one mechanism has one home.

### Consequences

- Good: "does resolution change the world?" is a command, `make episodes`, with a
  control arm.
- Good: the first measurement is honest and unwelcome. Over 21 sim-days on rules
  episodes pulled the first services invoice forward ~16h at +2.1% decisions —
  *and* the docking gap is large (proxy escalates 0.10 of outage meetings,
  episodes 0.72), so the dial moves base rates as well as resolution.
- Bad: that gap is an upper bound. The denominators are different constructs, so
  selection is inside it; separating them needs a shadow arm.
- Bad: off by default, so the shipped world does not use them — `episode.round`
  asks questions the golden cassette does not hold.
- Bad: the caps are judgements, chosen mean so that a binding cap shows up in
  `exit_reason`.
- Reverse it if: the gap survives recalibrating the one-shot's wording, or a live
  Jev run shows no macro effect beyond the A/A noise floor — then publish the
  finding and delete the mechanism rather than keep it switched off.

Long form: `docs/design/011-episodes.md`.
