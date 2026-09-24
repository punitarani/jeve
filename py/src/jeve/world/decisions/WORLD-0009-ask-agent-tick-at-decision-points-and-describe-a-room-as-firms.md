---
id: "WORLD-0009"
title: "Ask agent.tick at decision points, and describe a room as firms"
status: "accepted"
date: 2026-09-24
deciders: ["claude"]
scope: ["py/src/jeve/world/space.py", "py/src/jeve/decide/questions.py", "py/src/jeve/core/orgs.py", "py/migrations/0011_decision_points.sql", "py/tests/test_space.py", "py/tests/test_questions.py"]
tags: ["space", "encounters", "cost", "cache", "jev", "agent-decided"]
supersedes: ["WORLD-0003"]
superseded-by: null
relates-to: ["DECIDE-0001", "DECIDE-0004", "WORLD-0006", "WORLD-0007"]
confirmation: "cd py && uv run pytest tests/test_space.py tests/test_questions.py"
---

# WORLD-0009 — Ask agent.tick at decision points, and describe a room as firms

## Context and Problem Statement

WORLD-0003 asked every member of staff one `agent.tick` question every open
tick. The golden-20260920 field report showed the cost: `agent.tick` was 99.3% of
calls, an office worker was asked 5,331 times and cafe staff 8,783 times (and
answered "stay" 97 to 99% of the time). The roster listed every person present in
load order, so 615 distinct situations became 20,826 distinct requests. And
`on_their_mind` took four values, all about the outage: nobody could perceive
money. DECIDE-0001 already said agents are evaluated at decision points.

## Considered Options

- **Keep asking everyone every tick.** Most answers are known in advance, and
  each spends a draw a real decision could have used. Loses.
- **Ask only at schedule boundaries.** Flattens the lunch curve and freezes
  anyone in a shared zone between boundaries. Loses.
- **Ask at decision points, with a horizon the question states.** Taken.
- **List people by role; the model picks a person.** Unbounded: every
  permutation of a room is a new request. Loses.
- **At most three firms, a count in words; the model picks a firm, code the
  person.** Taken.

## Decision Outcome

Somebody is asked `agent.tick` on arrival, while away from their workplace, in
company from another firm, when what is on their mind changes, through lunch,
and on the hour; cafe staff alone behind their counter are not asked. A quiet
desk is asked about the next hour, everyone else about the next quarter.

The rest of WORLD-0003 stands: six zones; opening hours are a code rule, now per
role (`core.orgs.SHIFTS`); "here" means one of the two left their workplace;
encounters resolve among people co-located now, then everyone moves; and a
customer who presses the vendor about a broken module they use cuts the outage's
remaining time to a quarter, once, with the chain to billing carried by `causes`.

What is on somebody's mind is one typed key (`positions.mind`) picked in a fixed
order of salience: wages held, the outage, the firm short, a promise broken, a
customer lost, a colleague quit, the queue swamped, a rough week, payday,
nothing. Roles render as noun phrases with their article (`ROLE_WORDS`).

### Consequences

- Good: on a five-day rules census `agent.tick` asks fell from 4,200 to 1,972,
  and the description of a room is bounded where a roster of people was not.
- Good: money reaches mood, so the report's finding that situation barely moved
  it (0.01 to 0.09 against temperament's 0.38 to 0.56) can be re-measured.
- Bad: every `agent.tick` and `episode.round` wording changes; the golden
  cassette must be re-recorded (`LIVE=1 make e2e`).
- Bad: a coffee run from a quiet desk is quantised to the hour; the stated
  horizon is what keeps its rate right.
- Bad: whom in a firm somebody talks to is a draw, not a judgement.
- Reverse it if: a live run shows the lunch curve or the encounter rate
  collapsing against golden-20260920, or mood still ignores the situation.
