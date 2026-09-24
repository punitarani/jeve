---
id: WEB-0008
title: The hero camera is a director, not a clock
status: accepted
date: 2026-09-23
deciders: ["claude"]
scope: ["packages/world/src/attention.ts", "packages/world/src/index.ts", "packages/world/test/attention.test.ts", "apps/web/src/components/WorldHero.tsx"]
tags: ["hero", "camera", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["WEB-0002", "WEB-0003"]
confirmation: "pnpm --filter @jeve/world exec node --test test/attention.test.ts"
---

# WEB-0008 — The hero camera is a director, not a clock

## Context and Problem Statement

The homepage hero's camera was a round-robin on a timer: every seven seconds
it eased to the next entry on a fixed list — the town, then each building in
turn. The list has no idea where the people are, so it zoomed politely into an
empty law office while the whole town walked to lunch behind it. What is on
screen is the whole product demo; a camera that ignores the cast makes the
town look dead. The obvious fix — shuffle the same list — keeps the same bug.

## Considered Options

- **A fixed tour with people-aware stops.** Still a playlist: occupancy is
  sampled when the tour is built, so it goes stale the moment someone stands
  up, and it still cannot follow anything that moves. Loses.
- **Scripted beats** ("at 12s, dolly to the cafe"). Reads as authored, breaks
  the moment the simulation does something real, and doubles the fixture cost
  of every map change. Loses.
- **A director that scores every plausible scene each frame.** Taken. Rooms
  score by occupancy plus arrivals, the street scores by how many are crossing
  it, conversations and escalations are short-lease interrupts, and an empty
  world leaves only the wide town shot. A held shot gets dwell time, a
  challenger must clear hysteresis to cut it, and scenes unseen for a while
  earn a novelty bonus — so attention is sticky but never stuck, with no
  script to maintain.

## Decision Outcome

The hero's camera watches `WorldModel` every frame and looks wherever people
are: occupied rooms, the street while anyone is crossing it, a fresh
conversation, a just-fired escalation — and the whole town when nobody is out.
Empty buildings are never a shot.

The scores are the decision: `attention.ts` is one scorer per scene kind plus
the rhythm constants (dwell, hysteresis, novelty, leases). It is GL-free like
`WorldModel` — plain numbers in, a `ViewTarget` out — so the whole policy is
unit-tested without a browser. WEB-0002's "hero with no controls and an
automatic camera" still holds; this record only pins what "automatic" means.

### Consequences

- Good: the camera tracks a migration as it walks (each frame's scene is
  rebuilt from live positions), the lunch rush is always the shot, and a
  quiet hour still pans gently between three town framings.
- Bad: the tuning is a page of constants; a scene kind's feel lives in its
  score, not in a place you can point at. Explorer mode is untouched.
- What would reverse it: evidence that visitors read the motion as jitter —
  complaints about the camera cutting too eagerly, or watching-tests failing
  to find the people the camera was told to find.
