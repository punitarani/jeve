import { expect, test, type Page } from "@playwright/test";

/**
 * What the town looks like, asserted without reading a pixel (WEB-0004).
 *
 * The light is a pure function of the sim clock and `status()` reports it, so
 * this checks that the scene is lit for the hour on the clock and that the
 * handle other specs click through still has every field they use. The four
 * skies themselves are a unit test: `packages/world/test/sky.test.ts`.
 *
 * Works against a production build: nothing here needs the `debug` helpers.
 */

type Status = {
  label: string;
  minute: number;
  sky: string;
  sunIntensity: number;
  lamps: number;
  glOk: boolean;
  software: string | null;
  drawing: boolean;
  bubbles: number;
  seq: number;
  tick: number;
  live: boolean;
  replaying: boolean;
  visible: number;
  walking: number;
  agents: { id: string; x: number; y: number; floor: number; zone: string; visible: boolean }[];
};

async function status(page: Page): Promise<Status> {
  return page.evaluate(() => {
    const handle = (window as unknown as {
      __jeveWorld?: Record<string, { status(): unknown }>;
    }).__jeveWorld?.explore;
    if (!handle) throw new Error("no explore world mounted");
    return handle.status() as Status;
  }) as Promise<Status>;
}

test.describe.configure({ timeout: 120_000 });

test("the town is lit for the hour on the sim clock", async ({ page }) => {
  await page.goto("/world");
  await expect
    .poll(async () => (await status(page).catch(() => null))?.agents.length ?? 0, {
      timeout: 40_000,
    })
    .toBeGreaterThan(0);

  const now = await status(page);
  const clock = /(\d{2}):(\d{2})$/.exec(now.label);
  expect(clock, `a sim clock in "${now.label}"`).not.toBeNull();
  expect(now.minute).toBe(Number(clock![1]) * 60 + Number(clock![2]));
  expect(now.sky).toMatch(/^#[0-9a-f]{6}$/);
  expect(now.sunIntensity).toBeGreaterThan(0);
  expect(now.lamps).toBeGreaterThanOrEqual(0);
  expect(now.lamps).toBeLessThanOrEqual(1);
  // Lamps are for the dark: off through the working day, on through the night.
  if (now.minute >= 8 * 60 && now.minute <= 17 * 60) expect(now.lamps).toBe(0);
  if (now.minute >= 21 * 60 || now.minute <= 5 * 60) expect(now.lamps).toBe(1);

  // Everything the other specs read is still there.
  for (const key of ["seq", "tick", "label", "live", "replaying", "visible", "walking"]) {
    expect(now).toHaveProperty(key);
  }
  for (const key of ["glOk", "software", "drawing", "bubbles"]) {
    expect(now).toHaveProperty(key);
  }
});

test("the map says where one sits, and staff at their desks are on a seat", async ({
  page,
  request,
}) => {
  await page.goto("/world");
  await expect
    .poll(async () => (await status(page).catch(() => null))?.agents.length ?? 0, {
      timeout: 40_000,
    })
    .toBeGreaterThan(0);

  // The API the page itself is reading from.
  const api = await page.evaluate(() => {
    const entries = performance.getEntriesByType("resource") as PerformanceResourceTiming[];
    const map = entries.find((entry) => entry.name.endsWith("/world/map"));
    return map ? map.name : null;
  });
  expect(api, "the page fetched /world/map").not.toBeNull();
  const map = (await (await request.get(api!)).json()) as {
    tiles: string[][];
    seats: Record<string, [number, number][]>;
    buildings: { zone: string; floors: number; x0: number; y0: number; x1: number; y1: number }[];
    storeys: { zone: string; floor: number; x0: number; y0: number; tiles: string[][] }[];
  };

  // A seat is on a floor: `zone/floor`. The ground floor is in `tiles`; an
  // upper floor is a storey's own grid over its building's footprint.
  const kindAt = (zone: string, floor: number, x: number, y: number): string | undefined => {
    if (floor === 0) return map.tiles[y]?.[x];
    const storey = map.storeys.find((s) => s.zone === zone && s.floor === floor);
    return storey?.tiles[y - storey.y0]?.[x - storey.x0];
  };
  const SITTABLE = ["chair", "bench", "sofa"];
  let seats = 0;
  for (const [key, tiles] of Object.entries(map.seats)) {
    const [zone, floor] = key.split("/");
    for (const [x, y] of tiles) {
      seats++;
      expect(SITTABLE, `${key} (${x},${y})`).toContain(kindAt(zone!, Number(floor), x, y));
    }
  }
  expect(seats).toBeGreaterThan(0);
  // Every floor that has a chair on it has somewhere to sit listed; the
  // renderer draws whoever is standing still on one of these as seated.
  // Asked of every building the map has, whatever it is called.
  for (const b of map.buildings) {
    for (let floor = 0; floor < b.floors; floor++) {
      let chairs = 0;
      for (let y = b.y0; y <= b.y1; y++) {
        for (let x = b.x0; x <= b.x1; x++) {
          const kind = kindAt(b.zone, floor, x, y);
          if (kind === "chair" || kind === "sofa") chairs++;
        }
      }
      if (chairs > 0) expect(map.seats[`${b.zone}/${floor}`]?.length, `${b.zone}/${floor}`).toBeGreaterThan(0);
    }
  }
});
