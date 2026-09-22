---
id: WEB-0007
title: Storeys are per-floor instanced groups; the level cut is visibility; camera and haze derive from the map
status: accepted
date: 2026-09-22
deciders: ["claude"]
scope: ["packages/world/src/render.ts", "packages/world/src/voxels.ts", "packages/world/src/model.ts", "packages/world/src/index.ts", "apps/web/src/components/WorldExplorer.tsx", "apps/web/e2e/a-world.spec.ts"]
tags: ["three.js", "rendering", "storeys", "performance", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["WEB-0002", "WEB-0003", "WEB-0004", "WORLD-0006"]
confirmation: "cd apps/web && npx tsc --noEmit -p tsconfig.json"
---

# WEB-0007 — Storeys are per-floor instanced groups; the level cut is visibility; camera and haze derive from the map

## Context and Problem Statement

WORLD-0006 made the town a district of twelve firms with one to three storeys
each, and a team a floor. The renderer was built for one street of
single-storey buildings: one instanced mesh for every static voxel, a camera,
a fog and a pan limit sized in tiles that were right for a forty-tile town, and
a look (WEB-0004) whose buildings have no roof so the camera can see in. With a
slab over every ground floor the camera sees nothing of the room where a team
sits, which is the one place the causal chain now runs through. And the
district is twice the town: a CPU rasteriser (WEB-0003) drew it at a frame a
second.

## Considered Options

- **Transparent upper floors.** Blending sorts badly across instances, halves
  the fill rate on a software renderer, and reads as a ghost, not a building.
  Loses.
- **Rebuild the meshes for each cut.** A few thousand boxes re-uploaded per
  click, and a hero tour that stalled on every stop. Loses.
- **One instanced group per storey, and the cut as visibility.** Taken.

## Decision Outcome

Every static voxel carries the storey it belongs to, the renderer builds one lit and one glowing instanced mesh per floor, and the level cut is model state that the renderer mirrors as mesh visibility and the model applies to people: someone above the cut is neither drawn nor picked.

`voxels.ts` gives each box a `floor`; `render.ts` groups them into
`StoreyMeshes[]`, one lit mesh, one glow mesh and one pool mesh per floor, and
`applyLevelCut` sets `visible` on them from `model.levelCut`. `WorldModel.shown`
is the one rule for people, read by the renderer, by picking and by the
snapshot's `drawn`, so a test asserts the cut with no GPU. The explorer's
segmented control and a team row in the firm's panel both set it; the hero's
tour descends each building with storeys from the top floor down, cut at the
floor it looks into, and each mount has a model of its own so neither cut
leaks into the other.

Nothing in the renderer is sized in tiles any more: the camera's distance, the
fog's near and far, the pan margin, the cloud field and the shadow frustum are
multiples of the map's span, worked out in `build`. This amends two earlier
records without contradicting them. WEB-0003's "draw cheaply on a software
renderer" now also skips the outskirts, a third of the boxes and nothing anyone
walks on. WEB-0004's "never a roof" stands, with the parapet on the top storey
only: below it the next slab sits, and a storey under another is a full
`STOREY` tall whatever the kind.

### Consequences

- Good: the cut is a click, not a rebuild, and holds at any zoom.
- Good: the fixture proves it in a headless browser: `drawn` and `levelCut`
  are in the snapshot, and the specs read those, not pixels.
- Good: a taller district or a wider one needs no renderer change.
- Bad: three draw calls per storey, so a district three floors high is nine
  static draw calls where there was one; still a handful.
- Bad: the cut is global. Cutting to see one team's floor takes the top off
  every building in town.
- Reverse it if: the cut should be per building — then the group is per
  building and floor, and the control lives in the firm's panel alone — or a
  software renderer still cannot hold fifteen frames a second on the district.
