---
id: WORLD-0007
title: Movement is decided at decision points with a dwell, not every tick
status: accepted
date: 2026-09-22
deciders: ["claude"]
scope: ["py/src/jeve/world/space.py", "py/migrations/0010_wake.sql", "py/tests/test_space.py"]
tags: ["space", "cadence", "cost", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["WORLD-0003", "WORLD-0006", "DECIDE-0001", "DECIDE-0005", "CORE-0009"]
confirmation: "cd py && uv run pytest tests/test_space.py"
---

# WORLD-0007 — Movement is decided at decision points with a dwell, not every tick

## Context and Problem Statement

WORLD-0003 asked every member of staff `agent.tick` every open tick: thirty-
five quarter-hours a day, each a request whose answer was "stay at my desk"
thirty-two times out of thirty-five. At twenty-four staff that was 97% of
model spend; at two hundred and twenty-five it would have been eight thousand
decisions a day, most of them a person confirming they are still working.
DECIDE-0001 already said an agent is evaluated at a decision point — task
complete, an inbox item, a schedule boundary, a synchronous interaction, a
mandatory timer — and the tick had quietly become the decision point.

## Considered Options

- **Keep asking every tick and cache harder.** The room changes every tick,
  so the key rarely repeats; and the cost is the request, not the answer.
  Loses.
- **Ask the model how long it will stay.** A number the model cannot judge,
  and a second thing to get wrong per decision. Loses: pacing is code.
- **Decision points, with a dwell drawn in code.** Taken.

## Decision Outcome

A person is asked `agent.tick` when they arrive, when the stay they chose
runs out, when a module their firm runs on goes down, when someone from the
vendor of a module they know is down walks onto their floor, and at noon;
how long a stay lasts is a band of ticks drawn in code about the person and
the moment, never a question.

The bands are by kind of place, not by its name: an hour or two at their own
desk, a quarter or half hour anywhere else, one tick at a vendor's office.
The top of the longest band is the mandatory timer, so nobody goes two hours
unasked. `positions` carries `next_decision_sim` and `last_decision_sim`;
zero means due now, which is what a fresh seed and an arrival want. Within a
tick, those who are due decide from where they stand; encounters resolve
among everyone co-located, started by the ones who decided; the deciders
move; everybody whose day is over goes home. A person not asked this tick
can still be talked to. Mood is written at decision points and persists.

On rules over five days at 225 staff: 7.8 `agent.tick` decisions per person
per day instead of 35, 12,000 decisions instead of 43,500, and the ledger
still balances; the rules twin's odds of an outing were retuned from per
quarter-hour to per stretch of work so the cafe is not emptied by the change.

### Consequences

- Good: the cost of `agent.tick` is proportional to things happening, not to
  the clock; a five-day run is 2.7x faster on rules.
- Good: an outage is an interrupt. Everyone whose firm runs on the module is
  asked within the tick it goes down, which is when the question is worth
  asking.
- Bad: the town is stiller between decisions; whether it looks alive is a
  matter of the bands, which are data and bracketed by a test.
- Bad: the wording of the three prompts changed ("next", not "the next
  fifteen minutes"), so every recorded `agent.tick` answer is a miss until
  the next recording.
- Reverse it if: the tests that bracket decisions per person-day (6 to 16)
  or the two-hour timer cannot be kept while the world stays legible, or a
  flow needs the whole roster's judgement every tick.
