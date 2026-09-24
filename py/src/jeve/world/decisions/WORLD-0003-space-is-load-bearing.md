---
id: WORLD-0003
title: Space is load-bearing — zones, encounters, and an escalation that reaches billing
status: superseded
date: 2026-09-20
deciders: ["claude"]
scope: ["py/src/jeve/world/space.py", "py/src/jeve/world/map.py", "py/migrations/0003_space.sql", "py/tests/test_space.py"]
tags: ["space", "encounters", "causality", "jev", "agent-decided"]
supersedes: []
superseded-by: "WORLD-0009"
relates-to: ["WORLD-0001", "DECIDE-0001", "DECIDE-0003", "CORE-0003", "WEB-0001"]
confirmation: "cd py && uv run pytest tests/test_space.py"
---

# WORLD-0003 — Space is load-bearing — zones, encounters, and an escalation that reaches billing

## Context and Problem Statement

The requirement is not that people have coordinates. It is that where they are
changes what happens: co-location must drive encounters, and encounters must
alter the event graph. A map on which people wander while the economy runs
exactly as it did without them is decoration, and the requirement is unmet.

Jev constrains the design in one specific way: the questions in a request are
answered independently. "Where do you go next?" cannot depend on "whom did you
just talk to?" inside one call.

## Considered Options

- **Two calls per person per tick** — move, then ask about whoever is now there.
  Correct sequencing, double the cost, and the brief asked for one call. Loses.
- **Tile-level proximity for encounters.** Finer, and it makes behaviour depend
  on pathfinding details and seat assignment. Zone-level is what the brief
  specified and is enough to make meeting contingent on movement. Loses.
- **Every co-located pair can meet**, colleagues at their desks included. Buries
  the log in ~250 encounters a day between people who never moved. Loses.
- **One call about the present moment; encounters among people whom movement
  brought together; one code rule by which an encounter changes the world.** Taken.

## Decision Outcome

Each open tick, each member of staff makes one `agent.tick` decision from where
they stand now: where to go next, whether to talk, to whom, about what, their
mood, and — only when it is possible — whether to press the vendor about an
outage. Encounters resolve among people co-located *now*; then everyone moves.

Six zones: four buildings, the plaza, and `home` (off the map). Whether a
workplace is open is a code rule, so commuting is never asked of a model. The
town is built in code and served to the client, so the renderer and the A*
pathfinder cannot disagree about a wall. Someone counts as "here" only if being
in the same place took one of you leaving your workplace. People present are
described to Jev by role and firm under neutral labels, never by name or id.

The rule that makes space matter: when staff of a firm that subscribes to a
broken module meet a Tallybird employee and `raise_outage` is sampled true, a
`ticket.escalated` event cuts the outage's remaining time to a quarter (floor
30 minutes, once per incident) and its open tickets jump the queue. The chain is
then carried by citations: `incident.ended` cites the escalation, and a blocked
invoice run that finally succeeds cites `incident.ended`.

`agent.moved` is emitted on zone change only and is excluded from the unit
economics: one per person per tick would be ~770 a day, burying the outage and
improving cost-per-thousand-events for free.

In the recorded five-day run, a junior associate at Halloran & Pike walked to
the software office on Thursday and pressed Tallybird's support about invoicing:
1,005 minutes saved, the outage ended, 24 invoices went out. Every link was
decided by Jev. With encounters switched off, the same seed issues those
invoices later and blocks more runs; `test_space.py` asserts both.

### Consequences

- Good: "does space matter?" is a test with a control arm, not a claim.
- Good: a conversation in a cafe is reachable from an invoice by a recursive
  query over `causes`.
- Bad: the escalation rule is mine, not the domain's. "A quarter of the time
  left" is a plausible number, not a measured one.
- Bad: `agent.tick` is now ~80% of model calls and rarely shares one, since who
  is in the room varies. Still $0.007 per sim-day.
- Bad: Jev almost never sends anyone to the plaza (p about 0.00-0.01). It is a
  place people cross, not a place they go.
- Reverse it if: tile-level proximity is needed (queues, eavesdropping), or a
  second kind of consequence makes the single escalation rule look arbitrary.
