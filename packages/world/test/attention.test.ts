// The hero's camera is decided by where the people are, so it is tested as
// one: no browser, no GPU, a hand-written `World`. Node runs TypeScript as it
// stands:
//
//   node --test packages/world/test/attention.test.ts
//
// `attention.ts` imports types only, which is what makes that possible;
// keep it so.
import assert from "node:assert/strict";
import { test } from "node:test";

import type { TownMap } from "@jeve/contracts";
import { HeroCamera, type Body, type World } from "../src/attention.ts";

const map: TownMap = {
  width: 40,
  height: 28,
  tiles: [],
  zones: [],
  buildings: [
    {
      zone: "software_office",
      org_id: "tallybird",
      name: "Tallybird Software",
      x0: 2,
      y0: 2,
      x1: 15,
      y1: 10,
      door: [9, 10],
    },
    {
      zone: "law_office",
      org_id: "halloran",
      name: "Halloran & Pike LLP",
      x0: 24,
      y0: 2,
      x1: 37,
      y1: 10,
      door: [30, 10],
    },
    {
      zone: "accounting_office",
      org_id: "ledgerline",
      name: "Ledgerline Accounting",
      x0: 2,
      y0: 17,
      x1: 15,
      y1: 25,
      door: [9, 17],
    },
    {
      zone: "cafe",
      org_id: "thirdrail",
      name: "Third Rail Cafe",
      x0: 24,
      y0: 17,
      x1: 37,
      y1: 25,
      door: [30, 17],
    },
  ],
  crowd_spots: {},
  seats: {},
};

const body = (x: number, y: number, over: Partial<Body> = {}): Body => ({
  x,
  y,
  visible: true,
  walking: false,
  route: null,
  routeToZone: null,
  ...over,
});

const at = (x: number, y: number): [number, number] => [x, y];

function world(
  people: Record<string, Body>,
  crowd: { x: number; y: number }[] = [],
): World {
  return { map, walkers: new Map(Object.entries(people)), crowd };
}

/** Walk the director forward a second at a time, returning the key it holds. */
function run(camera: HeroCamera, w: World, from: number, seconds: number): string {
  let key = "";
  for (let t = 0; t <= seconds * 10; t++) {
    camera.frame(w, from + t * 100);
    key = camera.key;
  }
  return key;
}

test("an empty town is only ever the wide shot", () => {
  const camera = new HeroCamera();
  const w = world({});
  const view = camera.frame(w, 0);
  assert.ok(view.span >= 34, "fully zoomed out");
  assert.ok(camera.key.startsWith("town"));
});

test("everybody home is an empty town, whoever is on the payroll", () => {
  const camera = new HeroCamera();
  const w = world({
    "a.b.1": body(0, 0, { visible: false }),
    "c.d.2": body(0, 0, { visible: false }),
  });
  camera.frame(w, 0);
  assert.ok(camera.key.startsWith("town"));
});

test("a building with nobody in it is never the shot", () => {
  const camera = new HeroCamera();
  const w = world({
    "a.b.1": body(5, 5),
    "a.b.2": body(8, 5),
    "a.b.3": body(11, 5),
  });
  assert.equal(run(camera, w, 0, 1), "room:tallybird");
  // For minutes: halloran, ledgerline and thirdrail are empty, so no key of
  // theirs can ever come up — the old tour visited them all on a timer.
  for (let t = 2_000; t < 90_000; t += 4_500) {
    camera.frame(w, t);
    assert.notEqual(camera.key, "room:halloran");
    assert.notEqual(camera.key, "room:ledgerline");
    assert.notEqual(camera.key, "room:thirdrail");
  }
});

test("a migration is followed, both ends of the walk in frame", () => {
  const camera = new HeroCamera();
  // Four people leave tallybird for the cafe: the story is the corridor.
  const route = [at(9, 10), at(15, 12), at(22, 14), at(30, 17)];
  const w = world({
    "a.b.1": body(30, 6, { walking: true, route, routeToZone: "cafe" }),
    "a.b.2": body(26, 10, { walking: true, route, routeToZone: "cafe" }),
    "a.b.3": body(20, 14, { walking: true, route, routeToZone: "cafe" }),
    "a.b.4": body(14, 13, { walking: true, route, routeToZone: "cafe" }),
    "c.d.1": body(30, 21),
  });
  camera.frame(w, 0);
  const view = camera.frame(w, 500);
  assert.equal(camera.key, "street");
  // The frame sits between the ones still walking and where they are going.
  assert.ok(view.x > 12 && view.x < 30 && view.z > 8 && view.z < 18);
  assert.ok(view.span >= 14 && view.span <= 40);

  // And it tracks them: a second later the walkers have moved and so has it.
  w.walkers.get("a.b.1")!.x = 28;
  w.walkers.get("a.b.1")!.y = 8;
  const moved = camera.frame(w, 1_500);
  assert.ok(moved.x !== view.x || moved.z !== view.z, "the camera tracks");
});

test("one person crossing town is a small shot, not the whole map", () => {
  const camera = new HeroCamera();
  const w = world({
    "a.b.1": body(20, 14, {
      walking: true,
      route: [at(15, 11), at(20, 14), at(30, 17)],
      routeToZone: "cafe",
    }),
  });
  camera.frame(w, 0);
  assert.equal(camera.key, "street");
  assert.ok(camera.frame(w, 100).span < 30);
});

test("a fresh conversation beats a quiet room", () => {
  const camera = new HeroCamera();
  const w = world({
    "a.b.1": body(30, 6),
    "a.b.2": body(31, 6),
    "c.d.1": body(8, 21),
  });
  camera.frame(w, 0);
  assert.equal(camera.key, "room:halloran");
  camera.encounter("a.b.1", "a.b.2", 5_000);
  const view = camera.frame(w, 5_001);
  assert.equal(camera.key, "chat:a.b.1|a.b.2");
  assert.ok(Math.abs(view.x - 30.5) < 0.01 && Math.abs(view.z - 6) < 0.01);
  assert.ok(view.span <= 12, "close on the pair");
});

test("an escalation interrupts everything, briefly", () => {
  const camera = new HeroCamera();
  const w = world({
    "a.b.1": body(30, 6),
    "a.b.2": body(31, 6),
    "a.b.3": body(29, 7),
    "a.b.4": body(32, 7),
  });
  camera.frame(w, 0);
  camera.drama(30, 6, 5_000);
  camera.frame(w, 5_001);
  assert.equal(camera.key, "alert");
  // Six and a half seconds of drama, then it is a room like any other.
  assert.equal(run(camera, w, 12_000, 3), "room:halloran");
});

test("attention is sticky: a near-tie does not cut the shot", () => {
  const camera = new HeroCamera();
  const w = world({
    "a.b.1": body(5, 5),
    "a.b.2": body(8, 5),
    "a.b.3": body(11, 5),
    "a.b.4": body(5, 7),
    "a.b.5": body(8, 7),
    // Two walkers: interesting, but not clearly more than six at their desks.
    "c.d.1": body(15, 12, {
      walking: true,
      route: [at(9, 10), at(15, 12), at(30, 17)],
      routeToZone: "cafe",
    }),
    "c.d.2": body(16, 12, {
      walking: true,
      route: [at(9, 10), at(16, 12), at(30, 17)],
      routeToZone: "cafe",
    }),
  });
  camera.frame(w, 0);
  assert.equal(camera.key, "street");
  // The walkers arrive; five at their desks become the story and stay it.
  for (const b of w.walkers.values()) {
    if (!b.walking) continue;
    b.walking = false;
    b.route = null;
    b.x = 30;
    b.y = 21;
  }
  assert.equal(run(camera, w, 1_000, 6), "room:tallybird");
  assert.equal(run(camera, w, 8_000, 8), "room:tallybird");
});

test("the camera wanders between comparably busy rooms", () => {
  const camera = new HeroCamera();
  const w = world({
    "a.b.1": body(5, 5),
    "a.b.2": body(8, 5),
    "a.b.3": body(11, 5),
    "c.d.1": body(29, 6),
    "c.d.2": body(31, 6),
    "c.d.3": body(33, 6),
  });
  const first = run(camera, w, 0, 1);
  // Given twenty seconds the other room gets its visit: novelty wins a tie.
  const seen = new Set([first]);
  for (let t = 2_000; t < 60_000; t += 2_000) {
    camera.frame(w, t);
    seen.add(camera.key);
  }
  assert.ok(seen.has("room:tallybird") && seen.has("room:halloran"));
});

test("the crowd counts, but only to where the crowd is", () => {
  const camera = new HeroCamera();
  // A queue at the cafe, one clerk at ledgerline, nobody else out.
  const queue = [at(28, 20), at(30, 21), at(32, 20), at(29, 22), at(33, 21)].map(
    ([x, y]) => ({ x, y }),
  );
  const w = world({ "a.b.1": body(8, 21) }, queue);
  camera.frame(w, 0);
  assert.equal(camera.key, "room:thirdrail");
});
