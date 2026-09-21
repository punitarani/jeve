import { expect, test } from "@playwright/test";

/**
 * Gate 5: a human can complete the primary flow in a browser.
 *
 * Asserted rather than eyeballed. A screenshot proves a page rendered; it does
 * not prove that clicking an outage reveals what the outage caused, which is
 * the only thing this dashboard exists to show.
 *
 * Needs the stack up: `make db-up && make fixture && make api` and the web app.
 */

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.getByTestId("status-strip")).toBeVisible();
});

test("the world is on screen: clock, four orgs, modules, people", async ({
  page,
}) => {
  await expect(page.getByTestId("clock")).toContainText(/^d\d+ \w{3} \d\d:\d\d$/);

  for (const org of ["tallybird", "halloran", "ledgerline", "thirdrail"]) {
    await expect(page.getByTestId(`org-${org}`)).toBeVisible();
  }

  // Money is rendered from integer cents, so it must look like money.
  await expect(page.getByTestId("org-tallybird")).toContainText(/\$[\d,]+/);

  await expect(page.getByTestId("status-strip")).toContainText("24 staff");
  await expect(page.getByTestId("status-strip")).toContainText(
    "400 counterparties",
  );
});

test("no org is owed a negative amount", async ({ page }) => {
  // A receivable that went negative is money arriving that was never owed —
  // a balance sheet that lies while the ledger still sums to zero.
  for (const org of ["tallybird", "halloran", "ledgerline", "thirdrail"]) {
    await expect(page.getByTestId(`org-${org}`)).not.toContainText("-$");
  }
});

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

  const incident = page.locator('[data-kind="incident.started"]').first();
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
  const select = page.getByTestId("person-select");
  await expect(select).toBeVisible();

  const options = await select.locator("option").allTextContents();
  expect(options.length).toBe(24);

  // Pick someone who actually decides in the flows that are wired up.
  const decider = options.find(
    (o) => o.includes("office_manager") || o.includes("support"),
  );
  expect(decider, "no role in the fixture makes decisions").toBeTruthy();
  await select.selectOption({ label: decider! });

  const rows = page.getByTestId("decision-row");
  await expect(rows.first()).toBeVisible({ timeout: 10_000 });

  const first = rows.first();
  // Which decider answered — the research question, one row at a time.
  await expect(first).toContainText(/rules|jev|llm/);
  // Something was actually chosen, not left blank. Since WORLD-0003 the most
  // recent thing anyone decided is usually where to go next.
  await expect(first).toContainText(/pay|answer|queue|buy|file|next_zone/);
  // And this world is decided by the model, not by the rules twin.
  await expect(rows.filter({ hasText: "jev" }).first()).toBeVisible();
});

test("filtering to one org narrows the timeline", async ({ page }) => {
  const before = await page.locator(".ev").count();
  await page
    .getByTestId("org-thirdrail")
    .getByRole("button", { name: "only" })
    .click();
  await expect
    .poll(async () => page.locator(".ev").count(), { timeout: 10_000 })
    .toBeLessThan(before);

  const orgs = await page
    .locator(".ev")
    .evaluateAll((els) =>
      [...new Set(els.map((el) => el.children[1]?.textContent))].filter(Boolean),
    );
  expect(orgs).toEqual(["thirdrail"]);
});

test("encounters start filtered out, and the chip puts them back", async ({
  page,
}) => {
  const chip = page.getByTestId("kind-encounter");
  await expect(chip).toBeVisible();

  // The panel opens on signal: staff small-talk is offered, not shown.
  await expect(chip).toHaveAttribute("aria-pressed", "false");
  await expect(page.locator('.ev[data-kind="encounter"]')).toHaveCount(0);

  const before = await page.locator(".ev").count();
  await chip.click();
  await expect(chip).toHaveAttribute("aria-pressed", "true");
  await expect
    .poll(async () => page.locator(".ev").count(), { timeout: 10_000 })
    .toBeGreaterThan(before);

  // And it is reversible.
  await chip.click();
  await expect
    .poll(async () => page.locator('.ev[data-kind="encounter"]').count(), {
      timeout: 10_000,
    })
    .toBe(0);
});

test("a filtered-out kind still shows inside a cascade", async ({ page }) => {
  // An encounter is how an outage reaches a ticket (WORLD-0003). Hiding the
  // kind must not put a hole in the chain this dashboard exists to show.
  await page.locator('[data-kind="incident.started"]').first().click();
  await expect(page.locator(".ev.sel")).toHaveCount(1);
  await expect
    .poll(async () => page.locator(".ev.dim").count(), { timeout: 10_000 })
    .toBeGreaterThan(0);

  // Every encounter on screen earned its place by being causally related.
  await expect(
    page.locator('.ev[data-kind="encounter"][data-related="no"]'),
  ).toHaveCount(0);
});
