---
id: "MEM-0004"
title: "Who has met whom is a typed tie, and it shapes who is approached"
status: "accepted"
date: 2026-09-24
deciders: ["claude"]
scope: ["py/src/jeve/memory/ties.py", "py/migrations/0015_signal.sql", "py/src/jeve/decide/policy.py", "py/src/jeve/world/space.py", "py/tests/test_ties.py", "py/tests/test_query_plans.py"]
tags: ["memory", "relationships", "encounters", "episodes", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["MEM-0001", "MEM-0002", "MEM-0003", "WORLD-0008", "WORLD-0009", "WORLD-0013"]
confirmation: "cd py && uv run pytest tests/test_ties.py tests/test_query_plans.py"
---

# MEM-0004 — Who has met whom is a typed tie, and it shapes who is approached

## Context and Problem Statement

People met, talked, promised and argued, and none of it stayed. The next time
two of them were in the cafe, they were strangers. Nothing weighed whom
somebody walked over to, how a conversation read, or whether someone had a
friend at work. When the room had people from a firm, Jev was asked "with
whom?" with nothing to go on, and on a 60-day world it put at least 0.35 on
"other" in 30% of its answers. Social structure is what separates a town from
a crowd, and the research on generative agents counts it as the part that
stateless agents lack (docs/research/04 §3.4).

## Considered Options

- **One typed row per pair: how often they have met, and warmth −3..3,
  written by what happened between them.** Taken.
- **A free-text memory of each relationship.** Loses: generated, and read
  back (GEN-0001).
- **A friend list per person.** Loses: ties are symmetric, and a list says who
  is a friend, not how they came to be.

## Decision Outcome

`ties` holds one row per pair (`a < b`): meetings, warmth, first and last
meeting, and the last topic. Encounters, episodes and promises write it, and
questions read it as words.

- **Written by events, not asked.** A pleasant chat warms a tie a quarter of
  the time, and being asked about money cools it a quarter of the time. Money
  or an outage raised in a bad mood always cools it. In an episode, a promise
  warms and a refusal cools; pressing hard, or both ending on small talk,
  moves it too. A promise kept warms it by one, a broken one cools it by two.
  A tie crossing below zero is a falling-out: `relationship.soured`, friction.
  The first version warmed on every chat and cooled only in a bad mood: over
  half the pairs who met ended as friends, and almost nobody fell out.
- **Read as words.** The room, the conversation and the monthly career
  question say who is a friend and who someone has fallen out with. Jev never
  sees a number.
- **Whom, within a firm.** The model chooses the firm. Who in it is
  approached is a draw weighted by `approach_weight` (more for people met
  more and liked more). The rules twin picks the firm by headcount as before,
  then uses the same weights, on a sixth draw so earlier luck is unchanged.
  Weighting the whole room instead sent everyone to the barista they saw
  every day, and nobody with an outage ever reached the vendor; the space
  tests caught it.

### Consequences

- Good: most meetings were repeats before ties existed (87% on the rules
  twin, 93% under Jev, 60-day worlds). Ties do not make more of them. They
  make each repeat carry its history. Jev's "with whom?" reached for "other"
  in 14% of answers, against 30% before (same seeds).
- Good: kept and broken promises have a social cost that lasts. A creditor
  who was let down knows it, and so do the people they tell (MEM-0002).
- Bad: read for every person asked what to do, every tick. It is an index
  range over one person's ties (`test_query_plans`), and the table grows with
  the square of the town.
- Reverse if: warmth never changes what anyone decides. That would show as
  persona and topic distributions that do not move with `met` or `warmth`
  across the harness's seeds.
