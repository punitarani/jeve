"use client";

/**
 * The landing page's data fetch (WEB-0005).
 *
 * The page itself is a static file; the world's state is not. First paint
 * fetches here, in the browser, so the same HTML serves everyone and the
 * "API is not reachable" state is a client concern rather than a 500.
 */
import { useEffect, useState } from "react";
import type { SimEvent, WorldState } from "@jeve/contracts";
import { fetchLatestEvents, fetchState } from "@/lib/api";
import { Dashboard } from "./Dashboard";
import { WorldHero } from "./WorldHero";

type Loaded = { state: WorldState; events: SimEvent[] };

export function Landing() {
	const [data, setData] = useState<Loaded | null>(null);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		let cancelled = false;
		Promise.all([fetchState(), fetchLatestEvents(600)])
			.then(([state, page]) => {
				if (!cancelled) setData({ state, events: page.events });
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
				<pre className="panel pre-wrap">{error}</pre>
				<p className="muted">
					Start it with <code>make api</code>, and the world with{" "}
					<code>make fixture</code>.
				</p>
			</main>
		);
	}

	return (
		<>
			<WorldHero />
			{data === null ? (
				<main className="page-pad">
					<p className="muted">Loading the world…</p>
				</main>
			) : (
				<Dashboard initialState={data.state} initialEvents={data.events} />
			)}
		</>
	);
}
