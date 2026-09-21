// The sky is a pure function of the sim clock (WEB-0004), so it is tested as
// one: no browser, no GPU, no dependency. Node runs TypeScript as it stands:
//
//   node --test packages/world/test/sky.test.ts
//
// `sky.ts` imports nothing, which is what makes that possible; keep it so.
import assert from "node:assert/strict";
import { test } from "node:test";

import { minuteOfDay, skyAt } from "../src/sky.ts";

const at = (hours: number, minutes = 0) => hours * 60 + minutes;
const FOUR = { morning: at(7, 30), midday: at(12, 30), dusk: at(18, 30), night: at(2) };

function luminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16);
  return (0.2126 * ((n >> 16) & 255) + 0.7152 * ((n >> 8) & 255) + 0.0722 * (n & 255)) / 255;
}

test("the four times of day the audit looked at have four skies", () => {
  // Audit C3: 07:30, 12:30, 18:30 and 02:00 shared one sky and one light.
  const skies = Object.values(FOUR).map((minute) => skyAt(minute));
  assert.equal(new Set(skies.map((s) => s.top)).size, 4);
  assert.equal(new Set(skies.map((s) => s.bottom)).size, 4);
  assert.equal(new Set(skies.map((s) => s.sunColor)).size, 4);
  assert.equal(new Set(skies.map((s) => s.sunDirection.join())).size, 4);
});

test("night is lit, not black, and the lamps are on", () => {
  const night = skyAt(FOUR.night);
  const noon = skyAt(FOUR.midday);
  assert.equal(night.lamps, 1);
  assert.equal(noon.lamps, 0);
  assert.ok(night.sunIntensity > 0.5, "there is a moon");
  assert.ok(night.hemiIntensity >= noon.hemiIntensity, "the ambient carries the night");
  assert.ok(luminance(night.top) < 0.1 && luminance(noon.top) > 0.4);
  // Dusk: the windows are coming on while the sun is still up.
  const dusk = skyAt(FOUR.dusk);
  assert.ok(dusk.lamps > 0.5 && dusk.sunIntensity > 1);
});

test("the sun rises in the east, goes round by the south, and sets in the west", () => {
  const [mx, , mz] = skyAt(FOUR.morning).sunDirection;
  const [, ny, nz] = skyAt(FOUR.midday).sunDirection;
  const [dx] = skyAt(FOUR.dusk).sunDirection;
  assert.ok(mx > 0.5, "east is +x");
  assert.ok(mz > 0, "and a little south");
  assert.ok(nz > 0.4 && ny > 0.8, "south is +z, and high");
  assert.ok(dx < -0.5, "west is -x");
});

test("the light is never so low that a shadow is longer than the town", () => {
  for (let minute = 0; minute < 1440; minute += 5) {
    const [x, y, z] = skyAt(minute).sunDirection;
    assert.ok(Math.abs(Math.hypot(x, y, z) - 1) < 1e-9, "a unit vector");
    assert.ok(y >= Math.sin((13 * Math.PI) / 180), `elevation at ${minute}`);
  }
});

test("it changes smoothly: no tick jumps the light", () => {
  // A tick is fifteen sim-minutes. The renderer eases between them, but a
  // keyframe typed wrong would still show as a flash.
  for (let minute = 0; minute < 1440; minute += 15) {
    const a = skyAt(minute);
    const b = skyAt(minute + 15);
    assert.ok(Math.abs(a.sunIntensity - b.sunIntensity) < 0.6, `sun at ${minute}`);
    assert.ok(Math.abs(luminance(a.top) - luminance(b.top)) < 0.12, `sky at ${minute}`);
  }
});

test("it wraps: a minute past midnight is a minute past midnight", () => {
  assert.deepEqual(skyAt(1441), skyAt(1));
  assert.deepEqual(skyAt(-60), skyAt(23 * 60));
});

test("the minute comes from the sim clock's label, and noon when it cannot", () => {
  assert.equal(minuteOfDay("d2 Wed 02:00"), 120);
  assert.equal(minuteOfDay("d1 Tue 16:45"), 16 * 60 + 45);
  assert.equal(minuteOfDay(""), 720);
  assert.equal(minuteOfDay("paused"), 720);
});
