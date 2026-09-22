import { expect, test, type Page } from "@playwright/test";

/** What decided the world under test: `jev` for the fixture, else the rules twin. */
const POLICY = process.env.JEVE_E2E_POLICY ?? "jev";

/**
 * The voxel world (WEB-0002): the hero advances on its own, and clicking a
 * person shows the distribution Jev returned for their last decision.
 *
 * Named `a-` so it runs first: `make e2e` starts a paced daemon just before the
 * browser tests, and "seq increases" is only true while that daemon is ticking.
 *
 * Almost nothing here needs a GPU. Positions, interpolation and picking live in
 * a scene model that is plain arithmetic, exposed as `window.__jeveWorld`, so
 * these assertions hold in a headless browser whether or not WebGL came up. The
 * first test says which it was.
 */

/** The roster as the API serves it: counts and ids are read, never written down here. */
type State = {
  persons: Record<string, number>;
  orgs: { id: string; name: string }[];
};

type Status = {
  seq: number;
  tick: number;
  label: string;
  live: boolean;
  replaying: boolean;
  visible: number;
  walking: number;
  glOk: boolean;
  software: string | null;
  drawing: boolean;
  agents: { id: string; x: number; y: number; floor: number; zone: string; visible: boolean }[];
};

/**
 * The API the page is reading from: the build inlines it, so the test run
 * that built the page has it in the environment; a page that is already up
 * says so through the origin of its own `/world/map` fetch.
 */
async function apiOrigin(page: Page): Promise<string> {
  const fromEnv = process.env.NEXT_PUBLIC_JEVE_API;
  if (fromEnv) return fromEnv;
  const seen = await page.evaluate(() => {
    const entries = performance.getEntriesByType("resource") as PerformanceResourceTiming[];
    return entries.find((entry) => entry.name.endsWith("/world/map"))?.name ?? null;
  });
  return seen === null ? "http://127.0.0.1:8000" : seen.replace(/\/world\/map$/, "");
}

async function state(page: Page): Promise<State> {
  const response = await page.request.get(`${await apiOrigin(page)}/state`);
  expect(response.ok(), "GET /state").toBe(true);
  return (await response.json()) as State;
}

async function townMap(page: Page): Promise<{ width: number; height: number }> {
  const response = await page.request.get(`${await apiOrigin(page)}/world/map`);
  expect(response.ok(), "GET /world/map").toBe(true);
  return (await response.json()) as { width: number; height: number };
}

async function status(page: Page, mode: "hero" | "explore"): Promise<Status> {
  return page.evaluate((m) => {
    const handle = (window as unknown as {
      __jeveWorld?: Record<string, { status(): unknown }>;
    }).__jeveWorld?.[m];
    if (!handle) throw new Error(`no ${m} world mounted`);
    return handle.status() as Status;
  }, mode) as Promise<Status>;
}

async function ready(page: Page, mode: "hero" | "explore"): Promise<void> {
  // Everybody on the roster is in the scene, at home or not.
  const staff = (await state(page)).persons.staff ?? 0;
  expect(staff, "the roster has staff").toBeGreaterThan(0);
  const mounted = async () =>
    (await status(page, mode).catch(() => null))?.agents.length ?? 0;
  try {
    await expect.poll(mounted, { timeout: 25_000 }).toBe(staff);
  } catch {
    // Seen once on a machine that was also running another project's test
    // suite: the three.js chunk (~1 MB) never finished downloading, so the page
    // never hydrated. One reload, and the fact is recorded rather than hidden.
    test.info().annotations.push({
      type: "reloaded",
      description: `${mode} world did not mount within 25s; reloaded once`,
    });
    await page.reload();
    await expect.poll(mounted, { timeout: 40_000 }).toBe(staff);
  }
}

// Generous: `make e2e` runs this beside a simulation, an API and a fresh
// production server, often on a laptop that is doing something else as well.
test.describe.configure({ timeout: 120_000 });

test("WebGL: is there a GPU context in this browser?", async ({ page }) => {
  await page.goto("/");
  const gl = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("webgl2") ?? canvas.getContext("webgl");
    if (!context) return null;
    const info = context.getExtension("WEBGL_debug_renderer_info");
    return info ? String(context.getParameter(info.UNMASKED_RENDERER_WEBGL)) : "webgl";
  });
  test.info().annotations.push({ type: "webgl", description: gl ?? "UNAVAILABLE" });
  console.log(`webgl renderer: ${gl ?? "UNAVAILABLE"}`);

  await ready(page, "hero");
  // If the browser has WebGL, the scene must have used it. If it has not, the
  // page must still have come up — that is what the GL-free model is for.
  const hero = await status(page, "hero");
  expect(hero.glOk).toBe(gl !== null);
  // A CPU rasteriser is recognised as one, and gets the cheap picture.
  expect(hero.software !== null).toBe(/swiftshader|llvmpipe|software/i.test(gl ?? ""));
  await expect(page.getByTestId("world-hero")).toBeVisible();
  await expect(page.getByTestId("status-strip")).toBeVisible();
});

test("the hero is moving within ten seconds of page load", async ({ page }) => {
  const loaded = Date.now();
  await page.goto("/");
  await ready(page, "hero");

  // Live movement if the daemon is ticking, a replay of the last sim-hour if it
  // is not: either way somebody is walking, and soon.
  await expect
    .poll(async () => (await status(page, "hero")).walking, { timeout: 10_000 })
    .toBeGreaterThan(0);
  expect(Date.now() - loaded).toBeLessThan(10_000);

  const before = await status(page, "hero");
  await page.waitForTimeout(700);
  const after = await status(page, "hero");
  const moved = after.agents.filter((agent) => {
    const was = before.agents.find((b) => b.id === agent.id);
    return was && (was.x !== agent.x || was.y !== agent.y);
  });
  expect(moved.length).toBeGreaterThan(0);
  // The hero has no controls: nothing to grab, nothing to click through.
  await expect(page.getByTestId("world-hero").locator("button")).toHaveCount(0);
});

test("a hero nobody can see is not drawn, and the town goes on", async ({ page }) => {
  await page.goto("/");
  await ready(page, "hero");
  expect((await status(page, "hero")).drawing).toBe(true);

  // Scrolled past: drawing a town nobody is looking at sixty times a second
  // competes with the page the reader *is* looking at. Under a software
  // renderer on a busy machine it froze the tab.
  await page.getByTestId("person-panel").scrollIntoViewIfNeeded();
  await page.mouse.wheel(0, 2000);
  await expect
    .poll(async () => (await status(page, "hero")).drawing, { timeout: 5_000 })
    .toBe(false);

  // The model is not the picture: people keep walking while nothing is drawn.
  const before = await status(page, "hero");
  await page.waitForTimeout(1200);
  const after = await status(page, "hero");
  const still = after.agents.every((agent) => {
    const was = before.agents.find((b) => b.id === agent.id);
    return was !== undefined && was.x === agent.x && was.y === agent.y;
  });
  expect(still && before.walking > 0).toBe(false);

  await page.mouse.wheel(0, -4000);
  await expect
    .poll(async () => (await status(page, "hero")).drawing, { timeout: 5_000 })
    .toBe(true);
});

test("the hero advances on its own: seq increases", async ({ page }) => {
  await page.goto("/");
  await ready(page, "hero");
  const first = (await status(page, "hero")).seq;
  expect(first).toBeGreaterThan(0);

  await expect
    .poll(async () => (await status(page, "hero")).seq, {
      timeout: 45_000,
      intervals: [500],
      message: "seq never moved: is the sim daemon running and paced?",
    })
    .toBeGreaterThan(first);
  await expect(page.getByTestId("hero-live")).toBeVisible();
  await expect(page.getByTestId("hero-seq")).not.toHaveText(String(first));
});

test("clicking a person shows the distribution behind their last decision", async ({
  page,
}) => {
  await page.goto("/world");
  await ready(page, "explore");
  await expect(page.getByTestId("world-hint")).toBeVisible();

  // Somebody who is on the map and standing still, found from the model and
  // clicked at the pixel they are drawn at. Standing still first: a walker
  // has moved on by the time a slow machine delivers the click.
  const target = await page.evaluate(() => {
    const handle = (window as unknown as {
      __jeveWorld: Record<
        string,
        {
          status(): { agents: { id: string; visible: boolean; walking: boolean }[] };
          screenPositionOf(id: string): { x: number; y: number } | null;
        }
      >;
    }).__jeveWorld.explore!;
    const agents = handle.status().agents;
    for (const agent of [...agents.filter((a) => !a.walking), ...agents]) {
      const at = agent.visible ? handle.screenPositionOf(agent.id) : null;
      if (at && at.x > 40 && at.y > 40) return { id: agent.id, ...at };
    }
    return null;
  });
  expect(target, "nobody is on the map to click").not.toBeNull();

  const canvas = page.getByTestId("world-canvas");
  await canvas.click({ position: { x: target!.x, y: target!.y } });

  const panel = page.getByTestId("agent-panel");
  await expect(panel).toBeVisible();
  // Picking is nearest-person: whoever was clicked, a person came up.
  await expect(panel).toHaveAttribute("data-person", /\w+\.\w+\.\d+/);
  // Whichever policy decided this run: Jev in the recorded fixture, the rules
  // twin when the stack runs free between recordings (JEVE_E2E_POLICY).
  await expect(panel.getByTestId("decided-by")).toHaveText(POLICY);
  if (POLICY === "jev") await expect(panel).toContainText("typesafe/jev");

  // Only a model returns a distribution; the rules twin returns a verdict.
  if (POLICY !== "jev") return;
  const bars = panel.getByTestId("distribution-bar");
  expect(await bars.count()).toBeGreaterThanOrEqual(4);
  // A distribution, not a verdict: the probabilities of one question sum to one.
  const first = panel.getByTestId("distribution").first();
  const ps = await first
    .locator(".dist-p")
    .evaluateAll((els) => els.map((el) => Number(el.textContent)));
  expect(ps.reduce((a, b) => a + b, 0)).toBeGreaterThan(0.97);
  expect(ps.reduce((a, b) => a + b, 0)).toBeLessThan(1.03);
  await expect(panel).toContainText(/sampled, draw 0\.\d\d|judged \(argmax\)/);
});

test("clicking a building shows the firm's books", async ({ page }) => {
  await page.goto("/world");
  await ready(page, "explore");

  // The accountants, if the roster still has them; any firm otherwise.
  const orgs = (await state(page)).orgs;
  const org = orgs.find((o) => o.id === "ledgerline") ?? orgs[0];
  expect(org, "the roster has a firm").toBeDefined();
  const at = await page.evaluate((id) => {
    const handle = (window as unknown as {
      __jeveWorld: Record<
        string,
        { screenPositionOfBuilding(id: string): { x: number; y: number } | null }
      >;
    }).__jeveWorld.explore!;
    return handle.screenPositionOfBuilding(id);
  }, org!.id);
  expect(at).not.toBeNull();
  await page.getByTestId("world-canvas").click({ position: { x: at!.x, y: at!.y } });

  const panel = page.getByTestId("org-panel");
  await expect(panel).toBeVisible();
  await expect(panel).toHaveAttribute("data-org", org!.id);
  await expect(panel).toContainText(org!.name);
  await expect(panel.getByTestId("org-cash")).toContainText(/\$[\d,]+/);
  // A team is a floor (CORE-0012): the panel lists them, with who is in.
  expect(await panel.getByTestId("org-team").count()).toBeGreaterThan(0);
  await expect(panel.getByTestId("org-team").first()).toContainText(/\d+ of \d+ in/);
});

test("dragging pans the map instead of selecting", async ({ page }) => {
  await page.goto("/world");
  await ready(page, "explore");
  // The middle of the map: a fixed point on the ground, wherever anyone is
  // standing, and wherever the map's edges are.
  const map = await townMap(page);
  const centre: [number, number] = [Math.floor(map.width / 2), Math.floor(map.height / 2)];
  const fountain = () =>
    page.evaluate(([x, y]) => {
      const handle = (window as unknown as {
        __jeveWorld: Record<
          string,
          { screenPositionOfTile(x: number, y: number): { x: number; y: number } }
        >;
      }).__jeveWorld.explore!;
      return handle.screenPositionOfTile(x, y);
    }, centre);
  const before = await fountain();

  const box = (await page.getByTestId("world-canvas").boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 - 160, box.y + box.height / 2 - 40, {
    steps: 8,
  });
  await page.mouse.up();

  // The ground follows the pointer (damping settles over a few frames).
  await expect
    .poll(async () => before.x - (await fountain()).x, { timeout: 5_000 })
    .toBeGreaterThan(120);
  // A drag is not a click: nothing got selected.
  await expect(page.getByTestId("world-hint")).toBeVisible();
});
