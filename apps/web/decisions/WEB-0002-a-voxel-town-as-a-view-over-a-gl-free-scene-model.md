---
id: WEB-0002
title: A voxel town on the landing page, as a view over a GL-free scene model
status: accepted
date: 2026-09-20
deciders: ["claude"]
scope: ["packages/world/**", "apps/web/src/components/WorldHero.tsx", "apps/web/src/components/WorldExplorer.tsx", "apps/web/src/app/world/**", "apps/web/e2e/a-world.spec.ts"]
tags: ["three.js", "rendering", "testing", "agent-decided"]
supersedes: ["WEB-0001"]
superseded-by: null
relates-to: ["WORLD-0003", "API-0001", "SIM-0001", "DECIDE-0003"]
confirmation: "pnpm --filter @jeve/web exec tsc --noEmit"
---

# WEB-0002 — A voxel town on the landing page, as a view over a GL-free scene model

## Context and Problem Statement

WEB-0001 chose a causal timeline over a map, on the argument that a tile map is
where generative-agent demos spend their effort and learn nothing. That was
right while space was decorative. WORLD-0003 made it load-bearing: who is in the
cafe at lunch now decides when invoices go out, and a timeline cannot show
*that two people were in the same room*. The brief for session 2 also asks for
it directly: a three.js orthographic voxel world, as a landing-page hero and as
a full-page app, from one package.

The risk is testability. A canvas is opaque to a browser test, and headless
WebGL is not something to bet a green build on.

## Considered Options

- **Keep the timeline only.** Cheapest, and now hides the mechanism that
  matters. Loses.
- **A 2D canvas or SVG map.** Testable and light, but not what was asked for,
  and it would need its own projection and depth sorting anyway. Loses.
- **Raycast against instanced meshes for picking.** The idiomatic three.js
  answer. An instanced mesh's cached bounds go stale as instances move, there
  are at most a few dozen people, and it cannot run without a GPU. Loses.
- **Sprites or models from an asset pack.** Faster to something pretty; brings a
  licence to track for no gain over boxes. Loses.
- **A scene model that is plain arithmetic, with three.js as a view over it.** Taken.

## Decision Outcome

`@jeve/world` exports `mountWorld(container, options)`, used twice: a hero with
no controls and an automatic camera, and an explorer with pan, zoom and clicks.
Positions, interpolation and picking live in `WorldModel`, which never touches
WebGL; `WorldView` renders it with an orthographic isometric camera, one
instanced mesh for every static voxel and one per body part, flat-shaded, all
geometry procedural.

The server ticks coarsely and the client interpolates. Each `agent.moved` event
carries the tiles walked, so live movement from the `seq` stream and the idle
replay from the event log are the same mechanism. When `seq` stalls — a paused
daemon, sim-night, a fixture at its horizon — the hero replays the last sim-hour
of *recorded* movement and says so; a live event stops it at once.

Picking is nearest projected screen position, and building clicks unproject to
the ground plane and look the tile's zone up in the map. Both work with no GPU.
The model is exposed as `window.__jeveWorld`, so Playwright asserts positions
and clicks the pixel a person is drawn at, rather than comparing screenshots.
A failed WebGL context is caught: the page and every other spec still run.

Counterparties are not given positions. They are demand flows, drawn as a grey
sampled crowd whose *count* is real (last tick's cafe arrivals). Speech bubbles
show the typed topic of an encounter, only inside the viewport. The timeline
stays, below the hero: the town shows that something happened, the timeline
shows what it caused.

### Consequences

- Good: six browser specs cover the hero advancing, a click reaching a Jev
  distribution, a building panel, and pan-not-select — none by screenshot.
- Good: headless Chromium on this machine does provide WebGL (SwiftShader), and
  the first spec records which renderer it got, so a change shows up as a fact.
- Bad: three.js is ~170 kB gzipped on the landing page for a picture.
- Bad: the replay is honest but subtle. A visitor can be watching an hour ago;
  the pill says so, the town itself does not.
- Bad: no occlusion handling. Someone behind a wall from the camera is still
  pickable, because picking never asks what is in front.
- Reverse it if: agent counts reach the hundreds (then picking needs a spatial
  index and the crowd should become real), or the hero's bundle cost shows up
  in load metrics that anyone cares about.
