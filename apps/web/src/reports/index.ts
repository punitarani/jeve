/**
 * Published field reports: frozen reads of the world, one page each (WEB-0007).
 *
 * A report is data (`<slug>/data.json`) plus the prose written against
 * it, rendered by the same components as the live report at /reports. This
 * list is what /reports shows under "Published" and what the static export
 * pre-renders under /reports/<slug>; nothing is fetched to know it.
 */
export type Published = {
	slug: string;
	title: string;
	/** The report's own headline, shown on its card. */
	headline: string;
	summary: string;
	/** ISO date the report was published. */
	date: string;
	run: string;
	/** The one-line evidence footer on its card. */
	scope: string;
};

export const REPORTS: readonly Published[] = [
	{
		slug: "day-3-in-prod",
		title: "Day 3 in Prod",
		headline: "Consequences arrived. Tallybird lasted 22 days.",
		summary:
			"Only what happened after Day 1: three deploys treated as experiments on a running world, Day 1's eight recommendations measured in production, and the first firm to fail.",
		date: "2026-09-25",
		run: "golden-20260920",
		scope: "d232→d742 · 332,395 decisions · 3 deploys · 9 defects",
	},
	{
		slug: "day-1-in-prod",
		title: "Day 1 in Prod",
		headline: "232 days on one street, for 93 cents",
		summary:
			"The first ~40 hours of the production run, read straight from its database. The mechanics hold up; the economy, and what the agents can perceive, do not yet.",
		date: "2026-09-23",
		run: "golden-20260920",
		scope: "d232 · 202,934 decisions · 21 findings · 7 defects",
	},
];

export const findReport = (slug: string) => REPORTS.find((r) => r.slug === slug);
