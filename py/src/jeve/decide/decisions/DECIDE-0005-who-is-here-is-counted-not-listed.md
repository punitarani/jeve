---
id: DECIDE-0005
title: Who is here is counted, not listed — bounded state for agent.tick
status: accepted
date: 2026-09-22
deciders: ["claude"]
scope: ["py/src/jeve/decide/questions.py", "py/src/jeve/decide/policy.py", "py/tests/test_questions.py"]
tags: ["questions", "cache", "cost", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["DECIDE-0003", "DECIDE-0004", "WORLD-0003", "WORLD-0007", "MEM-0001"]
confirmation: "cd py && uv run pytest tests/test_questions.py"
---

# DECIDE-0005 — Who is here is counted, not listed — bounded state for agent.tick

## Context and Problem Statement

`agent.tick` used to put every co-located person into the state, one labelled
line each, and offer every one of them as somebody to talk to. On a street of
twenty-four that was a handful of lines; on a floor of twenty engineers it is
twenty lines and twenty-one options, the request grows with the room, and two
rooms that differ by one person never share a call. The cache key is the bytes
sent (DECIDE-0004), so the roster is the one input that made the key
combinatorial.

## Considered Options

- **List everyone, cap the list at some N.** Bounded, but which N are shown is
  arbitrary and the model is told nothing about the rest. Loses.
- **Name nobody: ask only whether they talk, and pick the partner in code.**
  Cheap, and it takes "whom" away from the model where it is the one social
  judgement worth asking. Loses.
- **Count the room; offer a few, chosen by code.** Taken.

## Decision Outcome

The state describes the room as counts by role and firm — "two engineers and
a salesperson from the software company; a paralegal from the law firm; and
three others" — for at most five firms, and `with_whom` offers at most six
people under neutral labels, chosen in code: the vendor's staff first when
their product is down, colleagues next, then the rest in a stable order.

`questions.candidates` is the one function that picks them and both policies
use it, so the labels a model chooses from and the people the rules twin picks
among are the same short list; the mapping from label to person lives in the
facts, never in the state. `roster_words` is the one function that describes
the room, so any two rooms with the same people in them by role and firm send
the same bytes and share a call. Phase 5's relationship strength is the second
sort key, not a different list.

### Consequences

- Good: a request is bounded whatever the floor holds — five groups, six
  candidates, one sentence — and the key space of `agent.tick` is small enough
  to share.
- Good: the model sees the shape of the room, which is what a person would
  notice, rather than a list it would not read.
- Bad: with more than six people worth talking to, code has already decided
  who is not an option. The priority is data in one function and can be
  wrong.
- Reverse it if: a measured run shows the model's choice of partner tracks
  the label order rather than the description, or a flow needs the model to
  pick among more than six.
