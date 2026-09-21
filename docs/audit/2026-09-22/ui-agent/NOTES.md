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
