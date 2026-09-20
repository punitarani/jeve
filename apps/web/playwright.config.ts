import { defineConfig } from "@playwright/test";

/**
 * The gate-5 check: a human can complete the primary flow in a browser.
 * Asserted, not eyeballed — a screenshot proves a page rendered, not that
 * clicking an incident reveals what it caused.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  // One worker, files in name order: `a-world` has to run while the paced
  // daemon is still ticking, and the rest do not care.
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.JEVE_WEB_URL ?? "http://127.0.0.1:3000",
    trace: "retain-on-failure",
  },
});
