---
id: WORLD-0008
title: A district of storeys — zones are buildings, teams are floors, encounters are per floor
status: accepted
date: 2026-09-22
deciders: ["claude"]
scope: ["py/src/jeve/world/map.py", "py/src/jeve/world/space.py", "py/src/jeve/world/seed_world.py", "py/migrations/0010_district.sql", "py/tests/test_layouts.py", "py/tests/test_space.py", "py/src/jeve/api/contracts.py"]
tags: ["space", "map", "floors", "encounters", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["WORLD-0003", "CORE-0012", "WEB-0002", "WEB-0004", "CORE-0009"]
confirmation: "cd py && uv run pytest tests/test_layouts.py tests/test_space.py"
---

# WORLD-0008 — A district of storeys — zones are buildings, teams are floors, encounters are per floor

## Context and Problem Statement

Twelve firms and two hundred and twenty-five people do not fit on one street
of four single-storey buildings, and a team is a thing people belong to that
the world had no word for. Putting everyone on one floor of a wider building
makes "who is here" the whole firm, every tick, which is the one input that
grows the cost of `agent.tick` combinatorially (it was 97% of spend at
twenty-four staff). The zone-level encounter rule from WORLD-0003 needs a
finer place than a firm without going to tiles.

## Considered Options

- **Wider single-storey buildings, teams as coloured areas.** Nothing to
  climb, nothing to cut away in the renderer, and the whole firm is
  co-located for every encounter. Loses on cost and on meaning.
- **Teams as separate buildings.** Thirty-odd lots, a town three times the
  size, and a firm no longer has an address. Loses.
- **Real storeys.** A building has floors; a team works on one; the ground
  floor is in the town grid and each upper floor is a local grid over the
  footprint, joined by a stair; the encounter place is the floor. Taken.

## Decision Outcome

A zone is a building, named by its firm's id, plus `plaza` and `home`; a
team is a floor of it; a place someone can be is a node `(x, y, floor)`;
people meet on a floor, not in a firm.

The district is placed by rule from the roster, never by tile number: three
rows of four lots, a building's width computed by furnishing each of its
layouts on a scratch shell and taking the widest, the avenue and the two
streets and the alley between. A stair tile sits in the far corner of every
floor of a multi-storey building and the pathfinder climbs it at a cost of
three tiles; the landing in front of it is kept clear so no layout can wall
a floor off. The ground floor of a building with floors above it gets a
lobby band by the door — reception, sofas, a kitchenette — furnished before
the team's layout, which is where colleagues from different floors meet.
Layouts are styles (`pods`, `offices`, `ranks`, `counter`, `rooms`,
`clinic`, `shopfloor`, `warehouse`, `gym`, `branch`), one function each in
the building's own frame, so the same function furnishes a twelve-tile floor
and a twenty-four-tile one; `test_layouts.py` builds every storey of the
real district and walks from the door, up the stair, to every seat.

`positions` gains a `floor`, `agent.moved` carries `from_floor`/`to_floor`
and a path of triples, and an encounter requires the same zone *and* floor.
Two people of one team on their own floor are at work, not meeting; two
people of one firm on different floors meeting in the lobby are. Where
someone stands is drawn from `("spot", person, zone, floor, arrival)`
(CORE-0009). Every firm keeps its own hours (`on_shift` reads the spec), so
the gym is peopled at seven and the offices at nine. Every retailer has a
till, and a till depends on a category of software, whoever sells it: a
second vendor's outage reaches a different set of tills.

### Consequences

- Good: "who is here" at a desk is a team, not a firm; the roster shown to
  Jev is bounded by the floor before any cap is applied.
- Good: the map serves storeys as data, so a renderer can cut the building
  at a level and a test can walk a floor without WebGL.
- Bad: upper floors are a second grid the pathfinder and the API must both
  understand; `kind(node)` looks up the storey by zone on every step.
- Bad: the plaza is now one crossing in a 81x56 district, further from most
  desks than before; whether anyone crosses it is Jev's, not the map's.
- Reverse it if: floors turn out to be where people are, not what they do —
  if lobbies and stairs never appear in a causal chain, the storey was
  decoration and one wide floor per firm was enough.
