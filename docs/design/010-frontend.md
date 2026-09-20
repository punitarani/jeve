# ADR-010 — Frontend rendering

Status: proposed · 2026-09-20

## Decision

**A state and event dashboard whose centrepiece is a causal timeline. No 2D map. No 3D.**

Smallville's map works because its world is spatial: who is near whom decides who talks, and
walking to the cafe is the story. jeve's world is organisational and transactional. Its
agents sit at desks. Where they are carries almost no information; **what flows between the
four orgs, and what caused what, carries all of it.** A tile map would spend the largest share
of frontend effort — sprites, pathfinding, a tile editor — on the least informative dimension
of the simulation.

And because the clock runs at about a sim-week per five real hours (ADR-001), a viewer almost
never watches an event happen. They arrive to history. "Legible at a glance" therefore means
**legible in retrospect**.

## What is on the screen

1. **Header strip.** Sim date and time; current speed; status (`running` / `paused` /
   `waiting on model`); today's spend against the budget.
2. **Org graph.** Four nodes, laid out by hand — four nodes do not need a graph library. Edges
   are the typed flows, animated as they occur and weighted by recent volume: invoices,
   payments, tickets, orders, engagements. Each node carries a health tile: cash, backlog,
   utilisation, and for Tallybird the status of each product module.
3. **Causal timeline — the hero.** Events in lanes per org, with `causes` links drawn between
   them (ADR-009). Click any event to highlight everything upstream and downstream.
   Incidents, month-ends, and payrolls are marked on the axis. *This is where "an outage at
   the software company cascaded into missed billing at the accounting firm" is either
   visible or it is not.*
4. **Since you were last here.** Computed in code from the log: the largest causal chains by
   downstream reach, threshold crossings, alerts. Prose optional and lazily rendered.
5. **Agent panel.** Roster with current activity. Select an agent: recent decisions with the
   **returned distributions drawn as bars**, the sampled outcome marked, the rule that chose
   it, escalation status; current beliefs; retrieved memories. Here the research question is
   inspectable — you can see what Jev thought and what the dice did with it.
6. **Health panel.** The degeneracy metrics and alerts from 02 §3.8, plus the ontology-gap
   rate and escalation rate.

Messages open to their typed speech act immediately; the prose rendering fills in when
ready. The sim never waits on it (ADR-002).

## What this costs us

- **Charm.** No little people walking about. The thing that made Smallville shareable is
  absent; a causal timeline does not make a good GIF.
- **Ambient life.** A dashboard looks the same busy or quiet at a glance. Animated flows on
  the org graph are the only mitigation.
- **Spatial mechanics.** Information diffusion through co-presence at the cafe
  (`docs/plan/scenario.md`) shows up as rows in a list, not as people at a table. Co-presence
  still exists in the model as a typed fact; it is simply not drawn.
- **A familiar metaphor.** Visitors must learn to read lanes and links.

If diffusion through the cafe turns out to be a star behaviour, the cheap upgrade is one
schematic strip — tables and who is sitting at them — not a world map.

## Stack

Next.js 16 (App Router). One client-side reducer folding the SSE stream over the `/state`
snapshot, keyed by `seq`. Types and zod validators generated from the Python contracts
(ADR-008). Plain SVG for the org graph and timeline; a small charting library for the metric
series, chosen against current docs when M3 is built. No global state library, no websocket:
the data flow is one-directional and SSE reconnects by `seq` with no gap (ADR-009).

## Alternatives rejected

| | Why not |
|---|---|
| **Smallville-style 2D map** | Above. Also couples the frontend to a spatial model the simulation does not otherwise need, and Smallville's clock was *driven by* its browser tab (01 §2) — the opposite of an ever-running server-side world. |
| **3D (three.js)** | Every cost of the map, several times over, for no added information. |
| **Log tail and tables only** | Sufficient to debug, not legible at a glance. Without the causal links drawn, cascades are invisible — and then the sim cannot meet its own bar. |
| **Observability tooling (Grafana and the like)** | Good for the health panel's time series, useless for causal structure and per-decision inspection. Possibly worth adding beside the app later; not instead of it. |

## Reverse if

- People who see it find it unreadable within a minute → the timeline is wrong; iterate
  there before adding a map.
- A spatial mechanic becomes causally important (queues at the cafe counter, who overhears
  whom) → add the schematic strip for that place only.
