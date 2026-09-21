// The screenshot harness: the same shots, every time, so a before and an after
// can be laid side by side. Run by `tools/shots.sh`; one phase per invocation.
//
//   node tools/screenshots.ts <phase> [tag]
//
//   WEB         the site                 (default http://localhost:3020)
//   API         the API behind it        (default http://127.0.0.1:8020)
//   SHOTS_OUT   where the PNGs go        (default docs/audit/shots)
//   SOFTWARE_GL=1  SwiftShader instead of the GPU, for the comparison shot
//
// Geometry is read from `GET /world/map`, never written down here: the town is
// allowed to grow and its doors to move.
//
// The GPU path (`--use-angle=metal`) is macOS. Elsewhere set SOFTWARE_GL=1.
import { createRequire } from "node:module";
import { appendFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
// Playwright is a dependency of the web app, not of the repo root.
const require = createRequire(resolve(ROOT, "apps/web/package.json"));
const { chromium } = require("@playwright/test");

const WEB = process.env.WEB ?? "http://localhost:3020";
const API = process.env.API ?? "http://127.0.0.1:8020";
const OUT = resolve(ROOT, process.env.SHOTS_OUT ?? "docs/audit/shots");
const LOG = resolve(OUT, "shots.jsonl");
const phase = process.argv[2] ?? "main";
const software = process.env.SOFTWARE_GL === "1";
mkdirSync(OUT, { recursive: true });

const VP = {
  d1440: { width: 1440, height: 900 },
  d1920: { width: 1920, height: 1080 },
  m390: { width: 390, height: 844 },
} as const;
type Viewport = keyof typeof VP;

type Building = { org_id: string; name: string; x0: number; y0: number; x1: number; y1: number };
const town: { buildings: Building[] } = await fetch(`${API}/world/map`)
  .then((r) => r.json())
  .catch(() => ({ buildings: [] }));
const ORGS = town.buildings.map((b) => b.org_id);
const centreOf = (org: string): [number, number] | null => {
  const b = town.buildings.find((x) => x.org_id === org);
  return b ? [(b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2] : null;
};

const browser = await chromium.launch({
  headless: true,
  args: software ? [] : ["--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist"],
});

async function open(vp: Viewport) {
  const mobile = vp === "m390";
  const c = await browser.newContext({
    viewport: VP[vp],
    deviceScaleFactor: mobile ? 3 : 1,
    isMobile: mobile,
    hasTouch: mobile,
  });
  return c.newPage();
}

async function ready(page: any, mode: string, timeout = 45000) {
  await page
    .waitForFunction((m: string) => (window as any).__jeveWorld?.[m]?.status().agents.length > 0, mode, { timeout })
    .catch(() => {});
}

async function shot(page: any, name: string, vp: string, route: string, note: string, opts: any = {}) {
  const fps = await page
    .evaluate(
      () =>
        new Promise<number>((res) => {
          let n = 0;
          const s = performance.now();
          const f = () => {
            n++;
            performance.now() - s > 1500 ? res(Math.round(n / 1.5)) : requestAnimationFrame(f);
          };
          requestAnimationFrame(f);
        }),
    )
    .catch(() => -1);
  const st = await page
    .evaluate(() => {
      const w = (window as any).__jeveWorld;
      const h = w?.hero ?? w?.explore;
      if (!h) return null;
      const { agents, ...rest } = h.status();
      return { ...rest, people: agents.length };
    })
    .catch(() => null);
  const file = `${name}--${vp}.png`;
  await page.screenshot({ path: `${OUT}/${file}`, ...opts });
  appendFileSync(
    LOG,
    JSON.stringify({
      file, route, vp, phase, fps, note,
      label: st?.label, seq: st?.seq, people: st?.people, walking: st?.walking, visible: st?.visible,
      live: st?.live, replaying: st?.replaying, software: st?.software ?? null,
      minute: st?.minute, sky: st?.sky, sunIntensity: st?.sunIntensity, lamps: st?.lamps,
    }) + "\n",
  );
  console.log(file, fps, "fps", st?.label ?? "");
}

const H = (page: any, fn: string, ...args: any[]) =>
  page.evaluate(([f, a]: any) => (window as any).__jeveWorld.explore[f](...a), [fn, args]);

async function focusBuilding(page: any, org: string) {
  const centre = centreOf(org);
  if (!centre) return;
  await focusTile(page, centre, 7);
}

// Drag a tile to the middle of the canvas and zoom in on it, `wheel` notches.
async function focusTile(page: any, centre: [number, number], wheel: number) {
  const box = await page.getByTestId("world-canvas").boundingBox();
  const c = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
  for (let i = 0; i < 3; i++) {
    const p = await H(page, "screenPositionOfTile", ...centre);
    await page.mouse.move(box.x + p.x, box.y + p.y);
    await page.mouse.down();
    await page.mouse.move(c.x, c.y, { steps: 6 });
    await page.mouse.up();
    await page.waitForTimeout(500);
    if (i === 0) {
      await page.mouse.move(c.x, c.y);
      for (let k = 0; k < wheel; k++) {
        await page.mouse.wheel(0, -240);
        await page.waitForTimeout(60);
      }
      await page.waitForTimeout(700);
    }
  }
}

// Click people until one has a last encounter, then ask for its dialogue.
async function dialogue(page: any, note: string, wait: number) {
  const ids: string[] = await page.evaluate(() =>
    (window as any).__jeveWorld.explore.status().agents.filter((a: any) => a.visible).map((a: any) => a.id),
  );
  for (const id of ids) {
    const p = await H(page, "screenPositionOf", id);
    if (!p) continue;
    await page.getByTestId("world-canvas").click({ position: { x: p.x, y: p.y } });
    await page.waitForTimeout(900);
    if (!(await page.getByTestId("imagine").count())) continue;
    await page.getByTestId("imagine").click();
    await page.waitForSelector("[data-testid=prose],[data-testid=no-prose]", { timeout: wait }).catch(() => {});
    await page.locator("[data-testid=prose],[data-testid=no-prose]").first().scrollIntoViewIfNeeded().catch(() => {});
    await page.waitForTimeout(500);
    await shot(page, "09-world-dialogue-loaded", "d1440", "/world", `${note} (${id})`);
    return;
  }
}

if (phase === "time") {
  const tag = process.argv[3];
  const page = await open("d1440");
  await page.goto(`${WEB}/world`);
  await ready(page, "explore");
  await page.waitForTimeout(2500);
  await shot(page, `08-world-${tag}`, "d1440", "/world", `sim-time ${tag}`);
  // The same hour from close to: the plaza, its lamps, and a building's windows.
  await focusTile(page, [(town as any).width / 2, (town as any).height / 2], 5);
  await shot(page, `08-world-${tag}-close`, "d1440", "/world", `sim-time ${tag}, the plaza from close to`);
}

if (phase === "main") {
  for (const vp of ["d1440", "d1920", "m390"] as const) {
    const page = await open(vp);
    await page.goto(`${WEB}/`);
    await ready(page, "hero");
    await shot(page, "01-landing-at-mount", vp, "/", "immediately after the hero mounted");
    if (vp === "d1440") {
      await page.waitForTimeout(process.env.SHOTS_FAST ? 3000 : 60000);
      await shot(page, "02-landing-plus-60s", vp, "/", "60 s later");
      await shot(page, "10-landing-full-page", vp, "/", "whole landing page", { fullPage: true });
      for (const id of ["status-strip", "timeline", "person-panel"]) {
        const el = page.locator(`[data-testid=${id}]`).first();
        if (!(await el.count())) continue;
        await el.scrollIntoViewIfNeeded();
        await page.waitForTimeout(400);
        await shot(page, `11-dashboard-${id}`, vp, "/", `dashboard section: ${id}`);
      }
      const inc = page.locator('[data-kind="incident.started"]').first();
      if (await inc.count()) {
        await inc.click();
        await page.waitForTimeout(1500);
        await inc.scrollIntoViewIfNeeded();
        await shot(page, "11-dashboard-cascade-selected", vp, "/", "timeline with an outage selected");
      }
    }
    await page.context().close();
  }
  for (const vp of ["d1440", "d1920", "m390"] as const) {
    const page = await open(vp);
    await page.goto(`${WEB}/world`);
    await ready(page, "explore");
    await page.waitForTimeout(2000);
    await shot(page, "04-world-default", vp, "/world", "default view");
    // Somebody away from their own building, if there is one: a more telling panel.
    const t = await page.evaluate((homes: Record<string, string>) => {
      const h = (window as any).__jeveWorld.explore;
      const a = h.status().agents.filter((x: any) => x.visible);
      const away = a.find((x: any) => homes[x.id.split(".")[0]] !== x.zone) ?? a[0];
      return away ? { id: away.id, ...h.screenPositionOf(away.id) } : null;
    }, Object.fromEntries((town.buildings as any[]).map((b) => [b.org_id, b.zone])));
    if (t) {
      await page.getByTestId("world-canvas").click({ position: { x: t.x, y: t.y } });
      await page.getByTestId("agent-panel").waitFor({ timeout: 15000 }).catch(() => {});
      await page.waitForTimeout(800);
      await shot(page, "06-world-agent-selected", vp, "/world", `agent ${t.id} selected`);
      if (vp === "m390") {
        await page.getByTestId("agent-panel").scrollIntoViewIfNeeded().catch(() => {});
        await shot(page, "12-mobile-agent-panel", vp, "/world", "agent panel scrolled into view on mobile");
      }
    }
    const cafe = ORGS.includes("thirdrail") ? "thirdrail" : ORGS[0];
    const b = cafe ? await H(page, "screenPositionOfBuilding", cafe) : null;
    if (b) {
      await page.getByTestId("world-canvas").click({ position: { x: b.x, y: b.y } });
      await page.getByTestId("org-panel").waitFor({ timeout: 15000 }).catch(() => {});
      await page.waitForTimeout(600);
      await shot(page, "07-world-building-selected", vp, "/world", `${cafe} selected`);
    }
    await page.context().close();
  }
  for (const org of ORGS) {
    const page = await open("d1440");
    await page.goto(`${WEB}/world`);
    await ready(page, "explore");
    await page.waitForTimeout(1500);
    await focusBuilding(page, org);
    await shot(page, `05-world-zoom-${org}`, "d1440", "/world", `zoomed to ${org}`);
    await page.context().close();
  }
  // People from close to (WEB-0004): somebody sitting at their desk, and
  // whoever is about in the plaza. Seats come from the map, not from here.
  {
    const page = await open("d1440");
    await page.goto(`${WEB}/world`);
    await ready(page, "explore");
    await page.waitForTimeout(1500);
    const seats: [number, number][] = Object.values((town as any).seats ?? {}).flat() as any;
    const sitter = await page.evaluate((tiles: [number, number][]) => {
      const a = (window as any).__jeveWorld.explore.status().agents.filter((x: any) => x.visible);
      return a.find((x: any) => tiles.some(([tx, ty]) => tx === x.x && ty === x.y)) ?? null;
    }, seats);
    if (sitter) {
      await focusTile(page, [sitter.x, sitter.y], 10);
      await shot(page, "14-people-seated-close", "d1440", "/world", `${sitter.id} at their desk, from close to`);
    }
    await page.context().close();
  }
  {
    const page = await open("d1440");
    await page.goto(`${WEB}/world`);
    await ready(page, "explore");
    await page.waitForTimeout(1500);
    await focusTile(page, [(town as any).width / 2, (town as any).height / 2], 8);
    await shot(page, "14-plaza-close", "d1440", "/world", "the fountain, benches and lamps, from close to");
    await page.context().close();
  }
}

if (phase === "bubble") {
  const page = await open("d1440");
  await page.goto(`${WEB}/world`);
  await ready(page, "explore");
  await page
    .waitForSelector("[data-testid=speech-bubble]", { timeout: 120000 })
    .catch(() => console.log("no bubble seen"));
  await page.waitForTimeout(400);
  await shot(page, "09-world-encounter-bubble", "d1440", "/world", "speech bubble for a live encounter");
}

if (phase === "landing-live") {
  const page = await open("d1440");
  await page.goto(`${WEB}/`);
  await ready(page, "hero");
  await shot(page, "01-landing-at-mount-LIVE", "d1440", "/", "immediately after mount, paced daemon running");
  await page.waitForTimeout(60000);
  await shot(page, "02-landing-plus-60s-LIVE", "d1440", "/", "60 s later, paced daemon running");
  const m = await open("m390");
  await m.goto(`${WEB}/`);
  await ready(m, "hero");
  await m.waitForTimeout(3000);
  await shot(m, "12-mobile-hero-LIVE", "m390", "/", "mobile hero, live");
}

// The world must be standing still: a new encounter remounts the panel and
// the prose with it.
if (phase === "dialogue-static") {
  const page = await open("d1440");
  await page.goto(`${WEB}/world`);
  await ready(page, "explore");
  await page.waitForTimeout(1500);
  await dialogue(page, "dialogue rendered for a last encounter, world static", 120000);
}

if (phase === "quiet") {
  for (const vp of ["d1440", "m390"] as const) {
    const page = await open(vp);
    await page.goto(`${WEB}/`);
    await ready(page, "hero");
    await page.waitForSelector("[data-testid=hero-replaying]", { timeout: 20000 }).catch(() => {});
    await page.waitForTimeout(5000);
    await shot(page, "03-hero-quiet-replaying", vp, "/", "daemon stopped: quiet mode");
    if (vp === "m390") await shot(page, "12-mobile-landing-full", vp, "/", "mobile landing, full page", { fullPage: true });
    await page.context().close();
  }
}

if (phase === "state") {
  const tag = process.argv[3];
  const page = await open("d1440");
  await page.goto(`${WEB}/`, { timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(6000);
  await shot(page, `13-state-${tag}-landing`, "d1440", "/", `state: ${tag}`);
  await page.goto(`${WEB}/world`, { timeout: 60000 }).catch(() => {});
  await page.waitForTimeout(6000);
  await shot(page, `13-state-${tag}-world`, "d1440", "/world", `state: ${tag}`);
  if (tag === "routes") {
    await page.goto(`${WEB}/nope`).catch(() => {});
    await page.waitForTimeout(1500);
    await shot(page, "10-route-404", "d1440", "/nope", "an unknown route");
  }
}

await browser.close();
