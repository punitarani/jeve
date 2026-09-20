---
id: WEB-0001
title: Show a state and event dashboard built around a causal timeline, not a map
status: accepted
date: 2026-09-20
deciders: ["punitarani"]
scope: []
tags: ["frontend", "visualisation"]
supersedes: []
superseded-by: null
relates-to: ["CORE-0007"]
confirmation: null
---

# WEB-0001 — Show a state and event dashboard built around a causal timeline, not a map

## Context and Problem Statement

Smallville's 2D map is the reason people shared it. Copying it is the obvious
move. But its world is spatial — who is near whom decides who talks — whereas
this world is organisational: agents sit at desks, and what flows between four
firms carries all the information.

## Considered Options

- **Smallville-style 2D map.** Rejected: spends the largest share of frontend
  effort on the least informative dimension, and couples the frontend to a
  spatial model the simulation does not otherwise need.
- **3D.** Every cost of the map, several times over, for no added information.
- **Log tail and tables.** Enough to debug, not legible at a glance; without
  causal links drawn, cascades are invisible.
- **State and event dashboard with a causal timeline.** Taken.

## Decision Outcome

The centrepiece is a causal timeline — events in lanes per org with their
`causes` links drawn — beside an org graph of typed flows and a person panel
showing the distribution a decision came from and the value that was sampled.

The clock runs at roughly a sim-week per five real hours, so a viewer almost
never watches an event happen; they arrive to history. "Legible at a glance"
therefore means legible in retrospect, which is what the timeline and a
computed "since you were last here" provide.

### Consequences

- Good: this is where the headline claim — an outage cascading into missed
  billing — is either visible or absent. A map could not show it.
- Good: the research question is inspectable, since you can see what the model
  returned and what the dice did with it.
- Bad: no charm. Nothing walks around; it does not make a good GIF.
- Bad: a dashboard looks the same busy or quiet; animated flows are the only
  mitigation.
- Reverse it if: people cannot read it within a minute, or a spatial mechanic
  becomes causally important — then add one schematic strip, not a world map.

Long form: `docs/design/010-frontend.md`.
