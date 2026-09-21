// A quick look at the town, between full sets from `tools/shots.sh`.
//
//   node tools/look.ts [what ...]      what: times | buildings | poses | walk | load | hero (default: all)
//
//   WEB        a dev server            (default http://localhost:3030)
//   API        the API behind it       (default http://127.0.0.1:8030)
//   LOOK_OUT   where the PNGs go       (default docs/audit/look)
//
// It needs `next dev`, not a production build: `debugClock` and `debugPose`
// hang on the world's handle only when `debug` is on (WEB-0004), and that is
// how four times of day and a seated, selected, talking person can be looked
// at without simulating four days and waiting for an encounter.
import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(resolve(ROOT, "apps/web/package.json"));
const { chromium } = require("@playwright/test");

const WEB = process.env.WEB ?? "http://localhost:3030";
const API = process.env.API ?? "http://127.0.0.1:8030";
const OUT = resolve(ROOT, process.env.LOOK_OUT ?? "docs/audit/look");
const what = process.argv.slice(2);
const wants = (name: string) => what.length === 0 || what.includes(name);
mkdirSync(OUT, { recursive: true });

type Building = { org_id: string; x0: number; y0: number; x1: number; y1: number };
const town: { buildings: Building[]; width: number; height: number } = await fetch(`${API}/world/map`).then((r) => r.json());

const browser = await chromium.launch({
  headless: true,
  args: process.env.SOFTWARE_GL === "1" ? [] : ["--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist"],
});
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });

async function open(route: string, mode: "hero" | "explore") {
  const page = await context.newPage();
  page.on("pageerror", (error: Error) => console.log("page error:", error.message));
  page.on("console", (message: any) => {
    if (message.type() === "error") console.log("console error:", message.text());
  });
  await page.goto(`${WEB}${route}`);
  await page.waitForFunction(
    (m: string) => (window as any).__jeveWorld?.[m]?.status().agents.length > 0 && (window as any).__jeveWorld[m].debugClock,
    mode,
    { timeout: 90000 },
  );
  await page.waitForTimeout(1500);
  return page;
}

const call = (page: any, mode: string, fn: string, ...args: any[]) =>
  page.evaluate(([m, f, a]: any) => (window as any).__jeveWorld[m][f](...a), [mode, fn, args]);

async function fps(page: any): Promise<number> {
  return page.evaluate(
    () =>
      new Promise<number>((res) => {
        let n = 0;
        const s = performance.now();
        const f = () => (++n, performance.now() - s > 1000 ? res(n) : requestAnimationFrame(f));
        requestAnimationFrame(f);
      }),
  );
}

async function snap(page: any, name: string) {
  const rate = await fps(page);
  await page.screenshot({ path: `${OUT}/${name}.png` });
  console.log(`${name}.png  ${rate} fps`);
}

async function zoomTo(page: any, x: number, y: number, wheel = 7) {
  const box = await page.getByTestId("world-canvas").boundingBox();
  const c = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  for (let i = 0; i < 3; i++) {
    const p = await call(page, "explore", "screenPositionOfTile", x, y);
    await page.mouse.move(box.x + p.x, box.y + p.y);
    await page.mouse.down();
    await page.mouse.move(c.x, c.y, { steps: 6 });
    await page.mouse.up();
    await page.waitForTimeout(400);
    if (i === 0) {
      await page.mouse.move(c.x, c.y);
      for (let k = 0; k < wheel; k++) {
        await page.mouse.wheel(0, -240);
        await page.waitForTimeout(50);
      }
      await page.waitForTimeout(600);
    }
  }
}

const TIMES: [string, number][] = [
  ["0730", 7 * 60 + 30],
  ["1230", 12 * 60 + 30],
  ["1830", 18 * 60 + 30],
  ["0200", 2 * 60],
];

if (wants("times")) {
  const page = await open("/world", "explore");
  for (const [tag, minute] of TIMES) {
    await call(page, "explore", "debugClock", minute);
    await page.waitForTimeout(600);
    await snap(page, `time-${tag}`);
  }
  const cafe = town.buildings.find((b) => b.org_id === "thirdrail") ?? town.buildings[0];
  if (cafe) {
    await zoomTo(page, (cafe.x0 + cafe.x1) / 2, cafe.y0 - 1, 5);
    for (const [tag, minute] of TIMES) {
      await call(page, "explore", "debugClock", minute);
      await page.waitForTimeout(600);
      await snap(page, `time-${tag}-close`);
    }
  }
  await page.close();
}

if (wants("buildings")) {
  for (const b of town.buildings) {
    const page = await open("/world", "explore");
    await zoomTo(page, (b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2);
    await snap(page, `building-${b.org_id}`);
    await page.close();
  }
}

if (wants("poses")) {
  const page = await open("/world", "explore");
  const people: { id: string; x: number; y: number }[] = await page.evaluate(() =>
    (window as any).__jeveWorld.explore.status().agents.filter((a: any) => a.visible),
  );
  // Two people who are near each other talk; the first is selected.
  let pair: [string, string] | null = null;
  let best = Infinity;
  for (const a of people) {
    for (const b of people) {
      const d = Math.hypot(a.x - b.x, a.y - b.y);
      if (a.id < b.id && d > 0.5 && d < best) [best, pair] = [d, [a.id, b.id]];
    }
  }
  if (pair) {
    const [a, b] = pair;
    await call(page, "explore", "debugPose", a, { talkingTo: b, selected: true, seated: false });
    await call(page, "explore", "debugPose", b, { talkingTo: a, seated: false });
    const at = people.find((p) => p.id === a)!;
    await zoomTo(page, at.x, at.y, 9);
    await snap(page, "pose-talking-selected");
    await call(page, "explore", "debugPose", a, { talkingTo: undefined, seated: true });
    await call(page, "explore", "debugPose", b, { talkingTo: undefined, seated: true });
    await page.waitForTimeout(700);
    await snap(page, "pose-seated-selected");
  }
  await page.close();
}

// A burst of frames while people are walking: a walk cycle cannot be judged
// from one. With no daemon ticking, the model replays the last recorded hour
// of movement within three seconds, which is walking enough.
if (wants("walk")) {
  const page = await open("/world", "explore");
  await zoomTo(page, town.width / 2, town.height / 2 + 1, 8);
  const box = await page.getByTestId("world-canvas").boundingBox();
  // Somebody whose position is changing and who is well inside the picture.
  const mover = () =>
    page.evaluate(async () => {
      const h = (window as any).__jeveWorld.explore;
      const before = new Map(h.status().agents.map((a: any) => [a.id, a]));
      await new Promise((r) => setTimeout(r, 70));
      for (const a of h.status().agents) {
        const was: any = before.get(a.id);
        const p = a.visible ? h.screenPositionOf(a.id) : null;
        if (!was || !p || (was.x === a.x && was.y === a.y)) continue;
        if (p.x > 280 && p.x < 780 && p.y > 320 && p.y < 560) return { id: a.id, ...p };
      }
      return null;
    });
  let shots = 0;
  for (let tries = 0; tries < 400 && shots < 8; tries++) {
    const at = await mover();
    if (!at) continue;
    await page.screenshot({
      path: `${OUT}/walk-${shots}.png`,
      clip: { x: box.x + at.x - 260, y: box.y + at.y - 300, width: 520, height: 520 },
    });
    console.log(`walk-${shots}.png  ${at.id}`);
    shots++;
  }
  await page.close();
}

// The town is growing to 104 staff and a crowd; the fixture has 24. Fill it to
// the renderer's capacity and see what the frame rate does.
if (wants("load")) {
  const page = await open("/world", "explore");
  for (const count of [0, 100, 232]) {
    const timer = setInterval(() => void call(page, "explore", "debugCrowd", count).catch(() => {}), 400);
    await page.waitForTimeout(1200);
    const drawn = await call(page, "explore", "debugCrowd", count);
    await snap(page, `load-${drawn}-extra`);
    clearInterval(timer);
  }
  await page.close();
}

if (wants("hero")) {
  const page = await open("/", "hero");
  await snap(page, "hero");
  await page.close();
}

await browser.close();
