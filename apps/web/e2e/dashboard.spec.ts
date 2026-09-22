import { expect, test, type Page } from "@playwright/test";

/** What decided the world under test: `jev` for the fixture, else the rules twin. */
const POLICY = process.env.JEVE_E2E_POLICY ?? "jev";

/**
 * Gate 5: a human can complete the primary flow in a browser.
 *
 * Asserted rather than eyeballed. A screenshot proves a page rendered; it does
 * not prove that clicking an outage reveals what the outage caused, which is
 * the only thing this dashboard exists to show.
 *
 * Needs the stack up: `make db-up && make fixture && make api` and the web app.
 */

/** The roster as the API serves it: counts and ids are read, never written down here. */
type State = {
  persons: Record<string, number>;
  orgs: { id: string; name: string }[];
};

/**
 * The API the page is reading from: the build inlines it, so the test run
 * that built the page has it in the environment; a page that is already up
 * says so through the origin of its own `/state` fetch.
 */
async function state(page: Page): Promise<State> {
  const fromEnv = process.env.NEXT_PUBLIC_JEVE_API;
  const seen =
    fromEnv ??
    (await page.evaluate(() => {
      const entries = performance.getEntriesByType("resource") as PerformanceResourceTiming[];
      return entries.find((entry) => /\/state$/.test(entry.name))?.name.replace(/\/state$/, "") ?? null;
    })) ??
    "http://127.0.0.1:8000";
  const response = await page.request.get(`${seen}/state`);
  expect(response.ok(), "GET /state").toBe(true);
  return (await response.json()) as State;
}

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("status-strip")).toBeVisible();
});

test("the world is on screen: clock, every org, modules, people", async ({
  page,
}) => {
  await expect(page.getByTestId("clock")).toContainText(/^d\d+ \w{3} \d\d:\d\d$/);

  const { orgs, persons } = await state(page);
  expect(orgs.length).toBeGreaterThan(0);
  // Every firm, in one read: a dozen rows probed one expectation at a time
  // is two dozen round trips to a page that is also drawing the town.
  const rows = await orgRows(page);
  for (const org of orgs) {
    expect(rows[org.id], org.id).toBeDefined();
    // Money is rendered from integer cents, so it must look like money.
    expect(rows[org.id]).toMatch(/\$[\d,]+/);
  }

  await expect(page.getByTestId("status-strip")).toContainText(`${persons.staff} staff`);
  await expect(page.getByTestId("status-strip")).toContainText(
    `${persons.counterparty} counterparties`,
  );
});

test("no org is owed a negative amount", async ({ page }) => {
  // A receivable that went negative is money arriving that was never owed —
  // a balance sheet that lies while the ledger still sums to zero.
  const rows = await orgRows(page);
  for (const org of (await state(page)).orgs) {
    expect(rows[org.id], org.id).toBeDefined();
    expect(rows[org.id]).not.toContain("-$");
  }
});

/** The text of every firm's row, by id, once the table has rendered. */
async function orgRows(page: Page): Promise<Record<string, string>> {
  await expect(page.locator('[data-testid^="org-"]').first()).toBeVisible();
  return page.locator('[data-testid^="org-"]').evaluateAll((els) =>
    Object.fromEntries(
      els.map((el) => [el.getAttribute("data-testid")!.slice(4), el.textContent ?? ""]),
    ),
  );
}

test("the primary flow: click an outage and follow what it caused", async ({
  page,
}) => {
  const timeline = page.getByTestId("timeline");
  await expect(timeline).toBeVisible();

  // `encounter` is filtered out by default, so `.ev` counts what is shown.
  // The substantial log this test needs is what was *loaded*, which the
  // header carries as "N of M events" (just "M events" with no filter on).
  const heading = page.getByRole("heading", { name: /causal timeline/i });
  const loaded = Number(
    (await heading.textContent())?.match(/(\d+) events/)?.[1],
  );
  expect(loaded).toBeGreaterThan(50);
  expect(await page.locator(".ev").count()).toBeGreaterThan(0);

  // Nothing is dimmed until something is selected.
  expect(await page.locator(".ev.dim").count()).toBe(0);

  // `.last()`, not `.first()`: the lane reads newest first, so the oldest
  // incident on screen — the one whose whole cascade is inside the loaded
  // window — is now at the bottom.
  const incident = page.locator('[data-kind="incident.started"]').last();
  await expect(incident).toBeVisible();
  await incident.click();

  // The cascade resolves: exactly one root, and the unrelated majority dims.
  await expect(page.locator(".ev.sel")).toHaveCount(1);
  await expect
    .poll(async () => page.locator(".ev.dim").count(), { timeout: 10_000 })
    .toBeGreaterThan(0);

  // The outage has consequences, and they are the ones the domain predicts.
  const relatedKinds = await page
    .locator('.ev[data-related="yes"]')
    .evaluateAll((els) => [
      ...new Set(els.map((el) => (el as HTMLElement).dataset.kind)),
    ]);
  expect(relatedKinds).toContain("incident.started");
  expect(
    relatedKinds.some((k) => k === "ticket.opened" || k === "invoice.blocked"),
  ).toBe(true);

  await expect(page.getByText(/showing the cascade around #\d+/i)).toBeVisible();

  // And it is reversible: clearing restores the full log.
  await page.getByRole("button", { name: "clear" }).click();
  await expect
    .poll(async () => page.locator(".ev.dim").count(), { timeout: 10_000 })
    .toBe(0);
});

test("a person's decisions show what was chosen and the draw behind it", async ({
  page,
}) => {
  const search = page.getByTestId("person-select");
  await expect(search).toBeVisible();
  await search.click();

  // A search, not a roster: the district's staff do not fit in a list, so
  // the empty query shows a screenful and never everyone. The options are
  // the list under the input, `role=option` each.
  const staff = (await state(page)).persons.staff ?? 0;
  expect(staff).toBeGreaterThan(30);
  await expect
    .poll(async () => page.getByRole("option").count(), { timeout: 10_000 })
    .toBeGreaterThan(0);
  const shown = await page.getByRole("option").count();
  expect(shown).toBeLessThanOrEqual(30);
  expect(shown).toBeLessThan(staff);

  // Pick someone who actually decides in the flows that are wired up: a
  // fragment of the role finds them wherever they are on the roster.
  let decider: string | null = null;
  for (const role of ["office_manager", "support"]) {
    await search.fill(role);
    const match = page.getByRole("option", { name: role }).first();
    const found = await match.waitFor({ timeout: 5_000 }).then(
      () => true,
      () => false,
    );
    if (!found) continue;
    decider = await match.textContent();
    await match.click();
    break;
  }
  expect(decider, "no role in the fixture makes decisions").toBeTruthy();
  // Each line is who, what they do and where — the same line the picked
  // person is then captioned with.
  expect(decider).toMatch(/^.+ — .+ @ .+/);
  await expect(page.getByTestId("person-picked")).toContainText(decider!);

  const rows = page.getByTestId("decision-row");
  await expect(rows.first()).toBeVisible({ timeout: 10_000 });

  const first = rows.first();
  // Which decider answered — the research question, one row at a time.
  await expect(first).toContainText(/rules|jev|llm/);
  // Something was actually chosen, not left blank. Since WORLD-0003 the most
  // recent thing anyone decided is usually where to go next.
  await expect(first).toContainText(/pay|answer|queue|buy|file|next_zone/);
  // And this world is decided by the model, not by the rules twin — unless
  // the stack is running free on rules between recordings (JEVE_E2E_POLICY).
  if (POLICY === "jev")
    await expect(rows.filter({ hasText: "jev" }).first()).toBeVisible();
});

/** Every org named by a row on screen, deduplicated. */
const orgsOnScreen = (page: Page) =>
  page
    .locator(".ev")
    .evaluateAll((els) =>
      [...new Set(els.map((el) => el.children[1]?.textContent))].filter(Boolean),
    );

test("filtering to one org narrows the timeline", async ({ page }) => {
  // The cafe, whose till makes it the noisiest row, if the roster still has
  // it; any firm otherwise.
  const orgs = (await state(page)).orgs;
  const org = (orgs.find((o) => o.id === "thirdrail") ?? orgs[0])!.id;
  // Not a row count: emptying the lane brings the foot of it into view and
  // pulls older pages in, so the count is the filter's side effect rather than
  // its claim. The claim is that nothing else is left.
  expect(await orgsOnScreen(page)).not.toEqual([org]);

  await page
    .getByTestId(`org-${org}`)
    .getByRole("button", { name: "only" })
    .click();

  await expect
    .poll(async () => orgsOnScreen(page), { timeout: 10_000 })
    .toEqual([org]);
});

test("encounters start filtered out, and the chip puts them back", async ({
  page,
}) => {
  const chip = page.getByTestId("kind-encounter");
  await expect(chip).toBeVisible();

  // The panel opens on signal: staff small-talk is offered, not shown.
  await expect(chip).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator('.ev[data-kind="encounter"]')).toHaveCount(0);

  // Counted on the kind itself rather than on the whole lane, whose total
  // scrollback can move underneath a comparison.
  await chip.click();
  await expect(chip).toHaveAttribute("aria-pressed", "true");
  await expect
    .poll(async () => page.locator('.ev[data-kind="encounter"]').count(), {
      timeout: 10_000,
    })
    .toBeGreaterThan(0);

  // And it is reversible.
  await chip.click();
  await expect
    .poll(async () => page.locator('.ev[data-kind="encounter"]').count(), {
      timeout: 10_000,
    })
    .toBe(0);
});

test("the kinds menu toggles kinds without closing on each pick", async ({
  page,
}) => {
  // The dropdown is the same filter the chips drive, one control instead of
  // one chip per kind. The menu must stay open between picks.
  await page.getByRole("button", { name: "event kinds" }).click();
  const item = page.getByTestId("menu-kind-payment.made");
  await expect(item).toBeVisible();
  await expect(item).toHaveAttribute("aria-checked", "true");

  const before = await page.locator(".ev").count();
  await item.click();
  await expect(item).toHaveAttribute("aria-checked", "false");
  await expect(item).toBeVisible(); // still open
  await expect
    .poll(async () => page.locator(".ev").count(), { timeout: 10_000 })
    .toBeLessThan(before);

  // "show all kinds" resets the filter and leaves the menu open.
  await page.getByTestId("menu-kind-payment.made").click();
  await page.getByTestId("menu-filter-none").click();
  await expect(page.locator(".ev")).toHaveCount(0, { timeout: 10_000 });
  await page.getByTestId("menu-filter-all").click();
  await expect
    .poll(async () => page.locator(".ev").count(), { timeout: 10_000 })
    .toBeGreaterThan(0);
  await page.keyboard.press("Escape");
  await expect(item).not.toBeVisible();
});

test("a filtered-out kind still shows inside a cascade", async ({ page }) => {
  // An encounter is how an outage reaches a ticket (WORLD-0003). Hiding the
  // kind must not put a hole in the chain this dashboard exists to show.
  await page.locator('[data-kind="incident.started"]').last().click();
  await expect(page.locator(".ev.sel")).toHaveCount(1);
  await expect
    .poll(async () => page.locator(".ev.dim").count(), { timeout: 10_000 })
    .toBeGreaterThan(0);

  // Every encounter on screen earned its place by being causally related.
  await expect(
    page.locator('.ev[data-kind="encounter"][data-related="no"]'),
  ).toHaveCount(0);
});

test("rows carry a readable line, not just the kind name", async ({ page }) => {
  // Everything on, so the encounter rows are on screen too. Scoped by testid:
  // Playwright matches an accessible name as a substring, and "tallybird"
  // contains "all", so a name query here would hit every org's row.
  await page.getByTestId("filter-all").click();

  // Where it happened and what it was about, not just the word "encounter".
  await expect(page.locator('.ev[data-kind="encounter"]').first()).toContainText(
    /encounter · \w/,
  );

  // And the kind that opens the primary flow names the module that went down.
  await expect(
    page.locator('.ev[data-kind="incident.started"]').first(),
  ).toContainText(/incident\.started · \w/);
});

/** The seq of every row on screen, top to bottom. */
const seqs = (page: Page) =>
  page.locator(".ev").evaluateAll((els) => els.map((el) => Number(el.dataset.seq)));

test("hiding every kind does not page the whole log", async ({ page }) => {
  // An empty lane keeps the foot of it on screen, and the scrollback loop
  // re-arms whenever the foot is visible. Without a guard, `hide all kinds`
  // walks the entire event table 200 rows at a time to show nothing.
  let pages = 0;
  await page.route("**/events?before=*", (route) => {
    pages += 1;
    return route.continue();
  });

  await page.getByRole("button", { name: "event kinds" }).click();
  await page.getByTestId("menu-filter-none").click();
  await expect(page.locator(".ev")).toHaveCount(0, { timeout: 10_000 });
  await page.keyboard.press("Escape");

  // Give the loop every chance to run away before asserting it did not.
  await page.waitForTimeout(2_000);
  expect(pages, "an empty lane must not fetch history it cannot show").toBe(0);
});

test("the timeline opens on the newest event", async ({ page }) => {
  // The clock runs far faster than real time, so a reader arrives to history:
  // what just happened is the top row, not the bottom one.
  const onScreen = await seqs(page);
  expect(onScreen.length).toBeGreaterThan(0);
  expect(onScreen).toEqual([...onScreen].sort((a, b) => b - a));
});

test("scrolling to the foot of the lane loads older events", async ({
  page,
}) => {
  const before = await seqs(page);
  const oldest = Math.min(...before);
  await expect(page.getByTestId("lane-end")).toContainText(/scroll|loading/i);

  const lane = page.getByTestId("timeline");
  await lane.evaluate((el) => el.scrollTo(0, el.scrollHeight));

  await expect
    .poll(async () => (await seqs(page)).length, { timeout: 15_000 })
    .toBeGreaterThan(before.length);

  // The new rows are older, and they arrived below the ones already there.
  const after = await seqs(page);
  expect(Math.min(...after)).toBeLessThan(oldest);
  expect(after.slice(0, before.length)).toEqual(before);
  expect(after).toEqual([...after].sort((a, b) => b - a));
});
