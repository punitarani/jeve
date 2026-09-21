# ui/look — notes, one entry per screenshot set

Sets are in `docs/audit/2026-09-22/ui-agent/<HHMM>/` in this worktree and are
not committed (large, public repo). "Before" is `docs/audit/2026-09-21/screenshots/`.
Started 19:17 local.

## 19:42 — set 1 (25 minutes in; lighting and people)

**Changed since the audit's pictures**

- Lighting (D2): hemisphere 1.15 → 0.55–1.0 by time of day, one sun with a
  PCF shadow map fitted to the whole town and snapped to texels, ACES filmic,
  sRGB out, and a shadowless fill from over the camera's shoulder so the two
  faces the camera sees never share one flat ambient.
- Occlusion baked per *corner* of every box (eight numbers, two instanced vec4
  attributes, a six-line `onBeforeCompile` patch) rather than one colour per
  box. WEB-0004 says why: one colour per instance can only grey a whole tile.
- Per-block colour jitter from a hash of tile coordinates; walls in three
  courses; a floor *material* per firm (carpet tiles, parquet, lino, a
  checkerboard) instead of a tint.
- Time of day (C3): `skyAt(minute)` in `sky.ts`, GL-free; sky gradient drawn by
  the renderer; windows, door signs and screens are unlit "glow" voxels; warm
  additive pools under windows and across floors at night.
  `status().sky / sunIntensity / lamps / minute` are there for a spec.
- People (D3): 13 boxes in one instanced mesh, head ≈ 41% of height, 0.92 tiles
  across the arms (was 0.46), role → hat table with a default, walk cycle phased
  by distance, idle breath, sitting, facing, selection ring + head marker.
  `MAX_PEOPLE` 256. Pose contract on `Walker` + `WorldModel.setPose` as briefed.
- Software GL: no shadow maps, blob shadows kept, AO and time of day stay.

**What I judge still wrong**

- The four buildings are still one layout in four colours (D4). Floors and
  wall heights differ now, which is not enough with labels hidden. Next.
- Nobody sits: `seats` is served but empty until the layouts have chairs.
- Windows read as floating pale squares; they want a frame.
- Night: walls go almost black next to warm floors. Dusk is good.
- I departed from "hemisphere ≈ 0.45": at 0.45 (÷π in three ≥ r155) a shadowed
  face is ~14% of albedo and goes black under ACES. It is 0.55 at noon with a
  0.55 fill; the sun is 2.9. Ratio sun:ambient is what the audit was about.
- Hero framing (town is ~30% of the frame) is `index.ts`'s camera, not mine.

**fps (`shots.jsonl`, real GPU, Apple M3 Max via ANGLE Metal)**: 61 in all 30
shots, including the four building zooms and 1920×1080.

**Next**: the four layouts + new tile kinds + plaza furniture + `seats`, then
exteriors (awning, pillars, lettered signs), then a poses look with `debugPose`.

## 20:08 — set 2 (51 minutes in; the four buildings, seats, the plaza)

**Changed since 19:42**

- One layout function per building in `map.py`, in the building's own (u, v)
  frame, published as `LAYOUTS`; `tests/test_layouts.py` furnishes each at
  today's bounds and at the coming ones (44/24/20/16 on 64×44) and walks from
  the door to every seat and spot. Plaza: benches facing the fountain,
  planters, lamps round the fountain and either side of every door.
- 13 new tile kinds in `TILE_KINDS`, each with a case in `voxels.ts`; furniture
  is drawn in its own frame and turned by its neighbours (chair → desk, screen
  → chair, shelf → wall, bench → fountain). `facingAt` is shared with the
  renderer so the chair and the person on it agree.
- `seats` on `GET /world/map` and in the zod `TownMap` = sittable tiles. Staff
  at their desks are now drawn seated through the renderer's one inference;
  the grey crowd sits when its spot is a chair.
- Exteriors: cafe awning + parasols on a terrace, law portico, software mast
  with a night light and bamboo, accounting window boxes. No roofs.
- Harness: added `14-people-seated-close`, `14-plaza-close` and an
  `08-world-<hour>-close` per time of day; `shots.jsonl` now logs
  `minute/sky/sunIntensity/lamps`. Nothing removed.
- `packages/world/test/sky.test.ts` (node's own runner, no dependency):
  `node --test packages/world/test/sky.test.ts`, 7 pass.

**Open these**: `05-world-zoom-*` (the four, tellable apart), `14-people-seated-close`,
`08-world-0200-night-close`, `08-world-1830-close`, `04-world-default`.

**What I judge still wrong**

- The cafe faces north, so its kitchen is against the wall nearest the camera
  and the baristas have their backs to us. True of any north-facing building;
  the offices were laid out to face the camera, the counter cannot be.
- The terrace is half hidden by the cafe's own wall and awning (it is on the
  far side). Parasols show; the people under them mostly do not.
- Selection and talking poses only show with `debugPose` (dev build); in the
  production harness nothing sets them yet, by design. `tools/look.ts poses`.
- Signs are still blank boards. Windows still unframed.
- At night outside walls are very dark and saturated.
- Not yet looked at under SwiftShader since the rewrite.

**fps**: 61 in all 35 shots (min 61, max 61), real GPU.

**Tests run**: `uv run pytest -q` 228 passed; ruff, ruff format, mypy clean;
tsc clean for @jeve/world, @jeve/contracts, @jeve/web; strict replay to
d1 12:30 served 1543/1543 calls from the cassette with the new layouts.

**Next**: SwiftShader check, a walking shot, lettered signs, window frames,
a browser spec for `status().sky`, then whatever the pictures say.
