---
id: WEB-0004
title: The town is lit, shadowed and peopled like a toy, not a diagram
status: accepted
date: 2026-09-20
deciders: ["claude"]
scope: ["packages/world/src/render.ts", "packages/world/src/voxels.ts", "packages/world/src/sky.ts", "packages/world/src/model.ts", "py/src/jeve/world/map.py", "packages/contracts/src/world.ts"]
tags: ["three.js", "rendering", "lighting", "characters", "agent-decided"]
supersedes: []
superseded-by: null
relates-to: ["WEB-0002", "WEB-0003", "WORLD-0003"]
confirmation: "pnpm --filter @jeve/world exec tsc --noEmit"
---

# WEB-0004 — The town is lit, shadowed and peopled like a toy, not a diagram

## Context and Problem Statement

The 2026-09-21 audit (`docs/audit/2026-09-21/README.md`) says why the town reads
as clip-art. D2: a hemisphere light at 1.15 lifts every face to its albedo,
nothing casts a shadow, nothing is occluded, one Lambert material fills large
surfaces flat. D3: a person is four thin boxes about 12 px tall that slide as a
rigid body. D4: three of four buildings come from one `_office()`, so with
labels hidden they are one building in three colours. And 07:30, 13:00 and
02:00 share one sky. The owner's target is a toy: Minecraft for the world,
Mario for the people, isometric, no roofs, a night that is shown. WEB-0002
(GL-free model) and WEB-0003 (cheap on software GL) still bind; no new dependency.

## Considered Options

- **A screen-space AO pass.** A full-screen pass every frame, the first thing
  to die on a CPU rasteriser, for a fixed camera that gains nothing from it. Loses.
- **One darkened colour per box**, as the brief literally asks. A box has one
  instance colour, so a floor tile by a wall goes uniformly grey and the
  gradient into the corner, which is the Minecraft look, is absent. Loses, narrowly.
- **Occlusion baked per corner when the voxels are built.** Taken. Eight numbers
  per box from a height field of the map, carried as two instanced vec4
  attributes and multiplied into the vertex colour by a small `onBeforeCompile`
  patch. No pass, no per-frame cost, and plain data on the `Voxel`.
- **Textures for variation.** Assets and a licence to track; a hash of the tile
  coordinates gives block-to-block jitter for nothing. Loses.
- **Point lights at night.** A per-fragment loop over every lamp. Night is
  carried by what is cheap everywhere: cool ambient, a moon, unlit emissive
  voxels for windows, lamps and screens, additive pools on the ground.
- **Infer poses in the renderer from events.** That is `index.ts`'s job. Loses.

## Decision Outcome

The look is computed, not post-processed: occlusion and colour jitter are baked per corner when the voxels are built, sky and sun are a pure function of the sim clock, shadow maps are for real GPUs only, and people are posed from four optional fields on the scene model.

Lighting: hemisphere near 0.45, one sun with PCF shadow maps (`PCFShadowMap`;
three 0.186 removed `PCFSoftShadowMap`), a shadow frustum fitted to the town and
snapped to whole texels, ACES filmic, sRGB out. On a software renderer shadow
maps are off and people keep a blob shadow; baked occlusion and time of day stay.

Time of day: `skyAt(minute)` in `sky.ts` is GL-free. The renderer draws its own
opaque sky, because the page's CSS gradient cannot know the sim clock, and
`snapshot()` reports `sky` and `sunIntensity` so a spec can tell four skies
apart without reading a pixel.

Buildings: one layout function each in `map.py`, parametric in the building's
bounds because the town is about to grow. Identity is furniture, parapets,
awnings and a sign, never a roof. A seat is a walkable `chair` tile, served as
`seats` on `GET /world/map`.

People: one instanced mesh for all parts of everyone (WEB-0002 said one per
part; with twelve parts and a shadow pass that is 24 draw calls for nothing), a
role-to-hat table with a default, limb swing phased by distance walked.
`Walker` gains optional `seated`, `facing`, `talkingTo`, `selected`, set only
through `WorldModel.setPose`. Production leaves them unset; the renderer's one
inference is that someone standing still on a seat tile sits.

### Consequences

- Good: four buildings tellable apart with labels hidden; four times of day at a glance.
- Good: none of it needs a GPU to test: occlusion is data, the sky a function, poses fields.
- Bad: the patch names a shader chunk (`color_vertex`). It throws if an upgrade
  renames it, so that is a failed scene build rather than a quietly flatter picture.
- Bad: no sun shadows on software GL, so the picture CI sees is not a visitor's.
- Bad: a 4096-square shadow map is 64 MB of GPU memory for a landing page.
- Reverse it if: the GPU path falls under 57 fps at 1440x900 with 104 staff, or
  the corner attributes cost more on a software renderer than the flat picture did.
