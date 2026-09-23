import { expect, test } from "@playwright/test";

/**
 * The reports: the live one at /reports and the published ones under it.
 *
 * Asserted by what a reader can do, not by pixels: the live page draws from
 * the API it was built against, the published one from nothing but its own
 * data, and both answer filters, sorts and hovers.
 *
 * Needs the stack up for the live half; the published half needs only the web
 * app.
 */

test("the live report draws the running world and links what was published", async ({ page }) => {
	await page.goto("/reports");
	await expect(page.getByTestId("report-status")).toBeVisible();
	await expect(page.getByTestId("report-status")).toContainText(/d\d+/);
	await expect(page.locator("h1")).toContainText(/\d+ days on one street, for /);
	await expect(page.getByTestId("vitals").locator(".vital")).toHaveCount(6);

	// Rule-based findings, one of which is always the ledger's.
	const findings = page.getByTestId("findings");
	await expect(findings).toContainText(/The books (do not )?balance/);
	const all = await findings.locator("article").count();
	await page.getByRole("button", { name: /^economy/ }).click();
	const economy = await findings.locator("article").count();
	expect(economy).toBeGreaterThan(0);
	expect(economy).toBeLessThanOrEqual(all);
	await page.getByRole("button", { name: /^all/ }).click();

	// All staff, sortable.
	const people = page.getByTestId("people");
	await expect(people.locator("tbody tr")).toHaveCount(24);
	await people.getByRole("columnheader", { name: "person" }).click();
	await expect(people.getByRole("columnheader", { name: "person" })).toHaveAttribute("aria-sort", "ascending");

	// The town is drawn, and the published report is one click away.
	await expect(page.getByTestId("town").locator("canvas")).toBeVisible();
	await page.getByTestId("report-day-1-in-prod").click();
	await expect(page).toHaveURL(/\/reports\/day-1-in-prod\/?$/);
	await expect(page.locator("h1")).toHaveText("232 days on one street, for 93 cents");
});

test("Day 1 in Prod is the report as published", async ({ page }) => {
	await page.goto("/reports/day-1-in-prod");
	await expect(page.locator("h1")).toHaveText("232 days on one street, for 93 cents");

	const findings = page.getByTestId("findings");
	await expect(findings.locator("article")).toHaveCount(21);
	await page.getByRole("button", { name: /^defects/ }).click();
	await expect(findings.locator("article")).toHaveCount(3);
	await page.getByRole("button", { name: /^all/ }).click();

	// Hide a firm from the cash chart; the last one visible cannot be hidden.
	const legend = page.locator("#economy .legend button");
	await expect(legend).toHaveCount(4);
	await legend.first().click();
	await expect(legend.first()).toHaveAttribute("aria-pressed", "false");
	await legend.first().click();

	// A chart answers a hover with the tooltip.
	const chart = page.locator("#economy .chart svg").first();
	await chart.scrollIntoViewIfNeeded();
	const box = await chart.boundingBox();
	if (!box) throw new Error("the cash chart has no box");
	await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
	await expect(page.getByRole("tooltip")).toContainText(/day \d+/);

	// The answer tables switch question set.
	const select = page.locator("#lt-sel");
	await select.selectOption("credit.decision");
	await expect(page.locator("#model table").last()).toContainText("P(any credit)");

	// The footer reaches the rest of the site.
	await expect(page.getByTestId("site-footer").getByRole("link", { name: "reports" })).toHaveAttribute(
		"aria-current",
		"page",
	);
});

test("an unknown report is not a page", async ({ page }) => {
	const response = await page.goto("/reports/no-such-report");
	expect(response?.status()).toBe(404);
});
