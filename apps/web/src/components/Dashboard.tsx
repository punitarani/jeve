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
import { Timeline } from "./Timeline";
import { PersonPanel } from "./PersonPanel";

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

	const down = state.modules.filter((m) => m.status === "down");
	const visible = useMemo(
		() => (org ? events.filter((e) => e.org_id === org) : events),
		[events, org],
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
						Causal timeline — {visible.length} events
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
