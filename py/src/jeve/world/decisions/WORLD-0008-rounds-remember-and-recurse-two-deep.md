---
id: "WORLD-0008"
title: "Conversations remember their rounds, end when people are done, and recurse two deep"
status: "accepted"
date: 2026-09-23
deciders: ["punitarani", "claude"]
scope: ["py/src/jeve/world/episodes.py", "py/src/jeve/decide/questions.py", "py/src/jeve/decide/policy.py", "py/src/jeve/memory/store.py", "py/migrations/0010_episode_depth_and_stall.sql", "py/tests/test_episodes.py"]
tags: ["episodes", "recursion", "realism", "memory", "resolution"]
supersedes: []
superseded-by: null
relates-to: ["WORLD-0006", "WORLD-0007", "MEM-0002", "DECIDE-0001", "DECIDE-0004"]
confirmation: "cd py && uv run pytest tests/test_episodes.py tests/test_questions.py"
---

# WORLD-0008 — Conversations remember their rounds, end when people are done, and recurse two deep

## Context and Problem Statement

The first live episodes, read from production after WORLD-0007, showed that
three rounds were mostly the same round. A round's state carried only sticky
flags, so 12 of 64 round questions were exact repeats and each answer was a
fresh draw of the same propensity: a customer 62% likely to press became about
95% likely over three rounds without anything happening. Nobody ever finished.
"Has the matter been dealt with?" is never true of an outage that is still
down, so the mean P(yes) was 0.13, and 7 of 8 episodes ended on the round cap.
Meanwhile two things MEM-0002 records were read by nothing: how many removes
someone was from first-hand news, and whether a promise was kept. The owner
asked for more recursion and more realism.

## Considered Options

- **Raise the round cap.** More rounds of the same question is more resampling.
- **Recurse more, nothing else.** Deeper trees of conversations that neither
  remember nor end would multiply the flaw.
- **Fix the round, then recurse where a dependency exists.** Taken.

## Decision Outcome

- **Rounds remember.** Every round's state says what each person did in the
  round just gone (by the same neutral labels) and how long they have been at
  it, so round N depends on round N−1.
- **People end conversations.** Each person is asked whether they have had
  their say, not whether the matter is solved. A round in which everyone repeats
  their last act ends the episode as `stalled`, as the recursion research
  pre-registered ("rounds continue only on state change").
- **Two deep, by dependency.** `MAX_DEPTH = 2`, in code and in migration 0010.
  After an episode closes, a pair who have a *different* outage or bill between
  them take it aside (never a matter an ancestor was about), and news can ripple
  a second table further. Both count against the daily ceiling.
- **Memory is read back.** How someone heard of an outage reaches their first
  decision to report it; a payer's last kept or broken promise to a firm reaches
  the next conversation about a bill. Both are appended only when present, so
  first-hand and first-time questions keep their bytes.

### Consequences

- Good: across five seeds on rules, 79% of episodes end with everyone done, 8%
  stall and 7% hit the cap; depth one and two both occur (71 and 36 of 382);
  outage minutes fall 24% against episodes off, up from 22%.
- Good: the rules twin models the same shape (pressing becomes less likely each
  round it is passed up; hearsay is acted on less), so it stays a fair control.
- Bad: the docking gap on rules barely moved (+0.51 to +0.47). Most of it is
  structural: an asker in an episode is offered `press` at a high base rate.
  The live gap (+0.59 before this record) is what round memory targets, and it
  has to be re-measured after deploy.
- Bad: every `episode.round` question changed, so the golden cassette must be
  re-recorded with a live key before strict replay passes.
- Bad: the ceiling of 12 a day now binds on about 7% of sim-days.
- Reverse the depth if: depth two stays a sliver after a live week, or the
  ceiling binds on most days.
