"use client";

/**
 * The dashboard (WEB-0001).
 *
 * The centrepiece is the causal timeline. The clock runs far faster than real
 * time, so a viewer almost never watches an event happen — they arrive to
 * history. "Legible at a glance" therefore means legible in retrospect, which
 * is what selecting an event and seeing what it caused provides.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import type { SimEvent, WorldState } from "@jeve/contracts";
import { ORG_COLORS } from "@jeve/contracts";
import { fetchCausal, fetchState, money } from "@/lib/api";
import { EVENT_TONE } from "@/lib/tone";
import { Timeline } from "./Timeline";
import { PersonPanel } from "./PersonPanel";

// `encounter` is ~67% of everything the timeline loads (ops/soak.md: 2,072 of
// the 3,097 events that survive the API's own BACKGROUND_EVENTS cut) — staff
// small-talk that buries the outage this panel exists to show. Same reasoning
// as that server-side cut, but one click away from coming back.
const HIDDEN_BY_DEFAULT = ["encounter"];

export function Dashboard({
	initialState,
	initialEvents,
}: {
	initialState: WorldState;
	initialEvents: SimEvent[];
}) {
	const [state, setState] = useState(initialState);
	const [events] = useState(initialEvents);
	const [selected, setSelected] = useState<number | null>(null);
	const [chain, setChain] = useState<Map<number, number> | null>(null);
	const [org, setOrg] = useState<string | null>(null);
	// The hidden set, not the selected set: the kinds only become known once
	// the events have arrived, so "a kind nobody ruled out is visible" has to
	// be the default, and the initial state has to be a literal.
	const [hidden, setHidden] = useState<ReadonlySet<string>>(
		() => new Set(HIDDEN_BY_DEFAULT),
	);

	// Refresh the header rather than the whole page: the timeline is a record
	// of what happened, so it does not need to move under the reader.
	useEffect(() => {
		const timer = setInterval(() => {
			fetchState()
				.then(setState)
				.catch(() => undefined);
		}, 5000);
		return () => clearInterval(timer);
	}, []);

	const select = useCallback(
		async (seq: number) => {
			if (selected === seq) {
				setSelected(null);
				setChain(null);
				return;
			}
			setSelected(seq);
			try {
				const [down, up] = await Promise.all([
					fetchCausal(seq, "down"),
					fetchCausal(seq, "up"),
				]);
				const depths = new Map<number, number>();
				for (const event of up.events)
					depths.set(event.seq, -(event.depth ?? 0));
				for (const event of down.events)
					depths.set(event.seq, event.depth ?? 0);
				setChain(depths);
			} catch {
				setChain(null);
			}
		},
		[selected],
	);

	// Counted over everything loaded rather than over `visible`: chip counts
	// that moved when you picked an org would reflow the row under the cursor.
	// Loudest first, so the kind worth switching off is the one you reach for.
	const kinds = useMemo(() => {
		const counts = new Map<string, number>();
		for (const event of events)
			counts.set(event.kind, (counts.get(event.kind) ?? 0) + 1);
		return [...counts].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
	}, [events]);

	const toggleKind = useCallback((kind: string) => {
		setHidden((prev) => {
			const next = new Set(prev);
			if (!next.delete(kind)) next.add(kind);
			return next;
		});
	}, []);

	const down = state.modules.filter((m) => m.status === "down");
	const visible = useMemo(
		() =>
			events.filter((event) => {
				if (org !== null && event.org_id !== org) return false;
				if (!hidden.has(event.kind)) return true;
				// A cascade is only legible whole. An event in the selected chain
				// stays on screen even when its kind is switched off, or following
				// what an outage caused would stop at the first encounter.
				return chain?.has(event.seq) ?? false;
			}),
		[events, org, hidden, chain],
	);

	return (
		<main>
			<header className="strip" data-testid="status-strip">
				<b>jeve</b>
				<span data-testid="clock">{state.clock.label}</span>
				<span className="muted">tick {state.clock.tick_seq}</span>
				<span className="muted">{state.clock.status}</span>
				<span>
					{down.length === 0 ? (
						<span className="pill up" data-testid="modules-ok">
							all modules up
						</span>
					) : (
						<span className="pill down" data-testid="modules-down">
							{down.map((m) => m.name).join(", ")} down
						</span>
					)}
				</span>
				<span className="muted">
					{state.persons.staff ?? 0} staff · {state.persons.counterparty ?? 0}{" "}
					counterparties
				</span>
				<span className="muted">
					{state.tickets.open} open tickets · {state.unpaid_invoices.n} unpaid
				</span>
			</header>

			<div className="grid">
				<section className="panel">
					<h2>Orgs</h2>
					<div className="orgrow muted">
						<span>Org</span>
						<span className="num">Cash</span>
						<span className="num">Receivable</span>
						<span className="num">Filter</span>
					</div>
					{state.orgs.map((o) => (
						<div className="orgrow" key={o.id} data-testid={`org-${o.id}`}>
							<span>
								<span
									className="swatch-sm"
									style={{ background: ORG_COLORS[o.id] ?? "#888" }}
								/>
								{o.name}
							</span>
							<span className="num">{money(o.cash_cents)}</span>
							<span className="num">{money(o.receivable_cents)}</span>
							<span className="num">
								<button
									className="link"
									onClick={() => setOrg(org === o.id ? null : o.id)}
								>
									{org === o.id ? "clear" : "only"}
								</button>
							</span>
						</div>
					))}
					<p className="muted fineprint">
						Money is held in integer cents and every movement is a balanced
						double-entry transaction the database checks.
					</p>
				</section>

				<PersonPanel />
			</div>

			<div className="section-pad">
				<section className="panel">
					<h2>
						Causal timeline — {visible.length}
						{visible.length !== events.length && <> of {events.length}</>} events
						{selected !== null && (
							<>
								{" "}
								· showing the cascade around #{selected}{" "}
								<button className="link" onClick={() => select(selected)}>
									clear
								</button>
							</>
						)}
					</h2>
					{kinds.length > 0 && (
						<div className="chips" data-testid="kind-filter">
							{kinds.map(([kind, n]) => (
								<button
									key={kind}
									type="button"
									className="pill chip"
									aria-pressed={!hidden.has(kind)}
									data-testid={`kind-${kind}`}
									onClick={() => toggleKind(kind)}
								>
									<span
										className="swatch-sm"
										style={{
											background: `var(--${EVENT_TONE[kind] ?? "neutral"})`,
										}}
									/>
									{kind} <span className="muted">{n}</span>
								</button>
							))}
							{/* Not "clear": the cascade's clear button is found by name.
							    These two carry testids because Playwright matches an
							    accessible name as a substring, and "tallybird" contains
							    "all" — every org row answers to that query too. */}
							<button
								type="button"
								className="link"
								data-testid="filter-all"
								onClick={() => setHidden(new Set())}
							>
								all
							</button>
							<button
								type="button"
								className="link"
								data-testid="filter-none"
								onClick={() => setHidden(new Set(kinds.map(([kind]) => kind)))}
							>
								none
							</button>
						</div>
					)}
					<Timeline
						events={visible}
						selected={selected}
						chain={chain}
						onSelect={select}
					/>
				</section>
			</div>
		</main>
	);
}
