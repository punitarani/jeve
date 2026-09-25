"use client";

/**
 * The landing page's data fetch (WEB-0005).
 *
 * The page itself is a static file; the world's state is not. First paint
 * fetches here, in the browser, so the same HTML serves everyone and the
 * "API is not reachable" state is a client concern rather than a 500.
 */
import { useEffect, useState } from "react";
import type { EventPage, WorldState } from "@jeve/contracts";
import { fetchLatestEvents, fetchState } from "@/lib/api";
import { RunnerLoader } from "@/components/block/runner-loader";
import { Card, CardContent } from "@/components/ui/card";
import { Dashboard } from "./Dashboard";
import { SiteFooter } from "./SiteFooter";
import { WorldHero } from "./WorldHero";

type Loaded = { state: WorldState; page: EventPage };

export function Landing() {
	const [data, setData] = useState<Loaded | null>(null);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		let cancelled = false;
		// Six hundred, not a scroll page's two hundred. `encounter` is most of
		// the log and the dashboard hides it by default, so 200 raw events is
		// about 50 rows on screen — and in a ten-day fixture the newest outage
		// sits some 900 events back. A first paint that reaches no incident is
		// a dashboard opening on nothing worth reading. Scrollback pages in
		// smaller steps from here.
		Promise.all([fetchState(), fetchLatestEvents(600)])
			.then(([state, page]) => {
				if (!cancelled) setData({ state, page });
			})
			.catch((reason: unknown) => {
				if (!cancelled)
					setError(reason instanceof Error ? reason.message : String(reason));
			});
		return () => {
			cancelled = true;
		};
	}, []);

	if (error !== null) {
		return (
			<main className="page-pad">
				<h1>jeve</h1>
				<p className="muted">The API is not reachable.</p>
				<Card size="sm">
					<CardContent>
						<pre className="pre-wrap m-0">{error}</pre>
					</CardContent>
				</Card>
				<p className="muted">
					Start it with <code>make api</code>, and the world with{" "}
					<code>make fixture</code>.
				</p>
				<SiteFooter />
			</main>
		);
	}

	return (
		<>
			<WorldHero />
			{data === null ? (
				<main className="page-pad flex min-h-[30vh] flex-col items-center justify-center">
					<RunnerLoader />
					<p className="muted">Loading the world…</p>
				</main>
			) : (
				<Dashboard initialState={data.state} initialPage={data.page} />
			)}
			<div className="section-pad">
				<SiteFooter>
					<span>jeve · four firms, one street, every decision a typed question</span>
				</SiteFooter>
			</div>
		</>
	);
}
