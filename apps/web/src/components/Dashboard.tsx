"use client";

/**
 * The dashboard (WEB-0001).
 *
 * The centrepiece is the causal timeline. The clock runs far faster than real
 * time, so a viewer almost never watches an event happen — they arrive to
 * history. "Legible at a glance" therefore means legible in retrospect, which
 * is what selecting an event and seeing what it caused provides.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ListFilter } from "lucide-react";
import { toast } from "sonner";
import type { EventPage, WorldState } from "@jeve/contracts";
import { fetchCausal, fetchOlderEvents, fetchState, money } from "@/lib/api";
import { EVENT_TONE, ORG_COLORS } from "@/lib/tone";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardAction,
	CardContent,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import {
	DropdownMenu,
	DropdownMenuCheckboxItem,
	DropdownMenuContent,
	DropdownMenuGroup,
	DropdownMenuItem,
	DropdownMenuLabel,
	DropdownMenuSeparator,
	DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Timeline } from "./Timeline";
import { PersonPanel } from "./PersonPanel";

// `encounter` is ~67% of everything the timeline loads (ops/soak.md: 2,072 of
// the 3,097 events that survive the API's own BACKGROUND_EVENTS cut) — staff
// small-talk that buries the outage this panel exists to show. Same reasoning
// as that server-side cut, but one click away from coming back.
const HIDDEN_BY_DEFAULT = ["encounter"];

// One screenful is about thirty rows, so a page is deep enough that reaching
// the end of one is a deliberate scroll rather than a flick, and small enough
// that the filters below can discard most of it without a visible stall.
const PAGE = 200;

export function Dashboard({
	initialState,
	initialPage,
}: {
	initialState: WorldState;
	initialPage: EventPage;
}) {
	const [state, setState] = useState(initialState);
	// Held ascending, always. Every memo below is order-independent, so one
	// canonical order means only the render has to know it reads backwards.
	const [events, setEvents] = useState(initialPage.events);
	const [cursor, setCursor] = useState(initialPage.oldest);
	const [more, setMore] = useState(initialPage.more);
	const [loading, setLoading] = useState(false);
	const [failed, setFailed] = useState<string | null>(null);
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

	const laneRef = useRef<HTMLDivElement | null>(null);
	const sentinelRef = useRef<HTMLDivElement | null>(null);
	const [atOldest, setAtOldest] = useState(false);

	// The lane is its own scroll container (globals.css `.lane`), so the
	// default viewport root is wrong: a sentinel below the lane's fold is
	// still on screen as far as the document is concerned, and every page
	// would load at once on first paint.
	useEffect(() => {
		const lane = laneRef.current;
		const sentinel = sentinelRef.current;
		if (lane === null || sentinel === null) return;
		const watcher = new IntersectionObserver(
			(entries) => setAtOldest(entries.some((entry) => entry.isIntersecting)),
			{ root: lane, rootMargin: "200px" },
		);
		watcher.observe(sentinel);
		return () => watcher.disconnect();
	}, []);

	const loadOlder = useCallback(async () => {
		setLoading(true);
		try {
			const page = await fetchOlderEvents(cursor, PAGE);
			// Older events go at the front of the ascending array, which is the
			// end of the rendered list — below the fold, so nothing the reader
			// is looking at moves.
			setEvents((prev) => [...page.events, ...prev]);
			setCursor(page.oldest);
			setMore(page.more);
		} catch (reason: unknown) {
			// Inline at the foot rather than a toast: unlike the cascade error
			// this state persists, and the retry belongs where the reader is
			// already looking.
			setFailed(reason instanceof Error ? reason.message : String(reason));
		} finally {
			setLoading(false);
		}
	}, [cursor]);

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
				toast.error("Could not load the causal chain.", {
					description: `event #${seq} stays selected; its cascade is not highlighted`,
				});
			}
		},
		[selected],
	);

	// Counted over everything loaded rather than over `visible`: chip counts
	// that moved when you picked an org would reflow the row under the cursor.
	// They do grow as scrollback pulls more history in, which is the same
	// promise — the number is what this page has seen. Loudest first, so the
	// kind worth switching off is the one you reach for.
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
	// Reversed here, at the one boundary where reading order matters. The clock
	// runs far faster than real time, so a reader arrives to history and wants
	// the most recent thing first; scrolling down then walks into the past,
	// which is also the direction the pages load.
	const visible = useMemo(
		() =>
			events
				.filter((event) => {
					if (org !== null && event.org_id !== org) return false;
					if (!hidden.has(event.kind)) return true;
					// A cascade is only legible whole. An event in the selected chain
					// stays on screen even when its kind is switched off, or following
					// what an outage caused would stop at the first encounter.
					return chain?.has(event.seq) ?? false;
				})
				.reverse(),
		[events, org, hidden, chain],
	);

	// The trigger is an effect rather than the observer callback, because the
	// kind and org filters are applied client-side: a page can arrive and leave
	// nothing new on screen, and an IntersectionObserver does not fire again
	// while its target stays intersecting. `loading` flipping back and
	// `loadOlder` changing with the cursor re-run this, so the lane keeps
	// pulling until it fills or the log runs out. `failed` stops the loop
	// rather than hammering an API that is already answering with an error.
	useEffect(() => {
		if (!atOldest || !more || loading || failed !== null) return;
		// An empty lane means the filters are hiding everything, not that there
		// is too little history: no page can put a row on screen. Without this,
		// `hide all kinds` walks the whole log, one request per 200 events, to
		// show nothing at the end of it.
		if (visible.length === 0) return;
		void loadOlder();
	}, [atOldest, more, loading, failed, visible.length, loadOlder]);

	const shownKinds = kinds.map(([kind]) => kind).filter((k) => !hidden.has(k));

	return (
		<main>
			<header className="strip" data-testid="status-strip">
				<b>jeve</b>
				<span data-testid="clock">{state.clock.label}</span>
				<span className="muted">tick {state.clock.tick_seq}</span>
				<span className="muted">{state.clock.status}</span>
				<span>
					{down.length === 0 ? (
						<Badge
							variant="outline"
							className="border-[var(--good)] text-[var(--good)]"
							data-testid="modules-ok"
						>
							all modules up
						</Badge>
					) : (
						<Badge variant="destructive" data-testid="modules-down">
							{down.map((m) => m.name).join(", ")} down
						</Badge>
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

			<div className="dash-grid">
				<Card size="sm">
					<CardHeader>
						<CardTitle className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
							Orgs
						</CardTitle>
					</CardHeader>
					<CardContent>
						<Table>
							<TableHeader>
								<TableRow className="text-muted-foreground hover:bg-transparent">
									<TableHead className="h-auto px-1.5 py-1 text-xs whitespace-normal">
										Org
									</TableHead>
									<TableHead className="num h-auto px-1.5 py-1 text-xs">
										Cash
									</TableHead>
									<TableHead className="num h-auto px-1.5 py-1 text-xs">
										Receivable
									</TableHead>
									<TableHead className="num h-auto px-1.5 py-1 text-xs">
										Filter
									</TableHead>
								</TableRow>
							</TableHeader>
							<TableBody>
								{state.orgs.map((o) => (
									<TableRow
										key={o.id}
										className="border-b-0 hover:bg-transparent"
										data-testid={`org-${o.id}`}
									>
										{/* whitespace-normal: the only text column — wrapping the name keeps
										    all four columns inside a phone-width card. */}
										<TableCell className="whitespace-normal px-1.5 py-1.5">
											<span
												className="swatch-sm"
												style={{ background: ORG_COLORS[o.id] ?? "#888" }}
											/>
											{o.name}
										</TableCell>
										<TableCell className="num px-1.5 py-1.5">
											{money(o.cash_cents)}
										</TableCell>
										<TableCell className="num px-1.5 py-1.5">
											{money(o.receivable_cents)}
										</TableCell>
										<TableCell className="num px-1.5 py-1.5">
											<Button
												variant="link"
												size="xs"
												className="h-auto p-0 text-[var(--mark)]"
												onClick={() => setOrg(org === o.id ? null : o.id)}
											>
												{org === o.id ? "clear" : "only"}
											</Button>
										</TableCell>
									</TableRow>
								))}
							</TableBody>
						</Table>
						<p className="muted fineprint">
							Money is held in integer cents and every movement is a balanced
							double-entry transaction the database checks.
						</p>
					</CardContent>
				</Card>

				<PersonPanel />
			</div>

			<div className="section-pad">
				<Card size="sm">
					<CardHeader>
						<CardTitle className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
							Causal timeline — {visible.length}
							{visible.length !== events.length && <> of {events.length}</>}{" "}
							events
							{selected !== null && (
								<>
									{" "}
									· showing the cascade around #{selected}{" "}
									<Button
										variant="link"
										size="xs"
										className="h-auto p-0 normal-case tracking-normal text-[var(--mark)]"
										onClick={() => select(selected)}
									>
										clear
									</Button>
								</>
							)}
						</CardTitle>
						<CardAction>
							<DropdownMenu>
								<DropdownMenuTrigger
									render={
										<Button variant="outline" size="xs">
											<ListFilter />
											event kinds
										</Button>
									}
								/>
								<DropdownMenuContent align="end" className="w-56">
									{/* Base UI: GroupLabel needs its items inside a Menu.Group. */}
									<DropdownMenuGroup>
										<DropdownMenuLabel>
											Kinds on the timeline
										</DropdownMenuLabel>
										{kinds.map(([kind, n]) => (
											<DropdownMenuCheckboxItem
												key={kind}
												checked={!hidden.has(kind)}
												closeOnClick={false}
												onCheckedChange={() => toggleKind(kind)}
												data-testid={`menu-kind-${kind}`}
											>
												<span
													className="swatch-sm"
													style={{
														background: `var(--${EVENT_TONE[kind] ?? "neutral"})`,
													}}
												/>
												{kind}
												<span className="ml-auto text-muted-foreground">{n}</span>
											</DropdownMenuCheckboxItem>
										))}
									</DropdownMenuGroup>
									<DropdownMenuSeparator />
									<DropdownMenuItem
										closeOnClick={false}
										onClick={() => setHidden(new Set())}
										data-testid="menu-filter-all"
									>
										show all kinds
									</DropdownMenuItem>
									<DropdownMenuItem
										closeOnClick={false}
										onClick={() =>
											setHidden(new Set(kinds.map(([kind]) => kind)))
										}
										data-testid="menu-filter-none"
									>
										hide all kinds
									</DropdownMenuItem>
								</DropdownMenuContent>
							</DropdownMenu>
						</CardAction>
					</CardHeader>
					<CardContent>
						{kinds.length > 0 && (
							<ToggleGroup
								multiple
								value={shownKinds}
								onValueChange={(next) =>
									setHidden(
										new Set(
											kinds
												.map(([kind]) => kind)
												.filter((kind) => !next.includes(kind)),
										),
									)
								}
								spacing={6}
								className="mb-2.5 w-full flex-wrap"
								data-testid="kind-filter"
							>
								{kinds.map(([kind, n]) => (
									<ToggleGroupItem
										key={kind}
										value={kind}
										size="sm"
										className="h-5 rounded-full border border-border px-2 text-[11px] font-normal opacity-45 aria-pressed:opacity-100 hover:border-foreground hover:bg-transparent"
										data-testid={`kind-${kind}`}
									>
										<span
											className="swatch-sm"
											style={{
												background: `var(--${EVENT_TONE[kind] ?? "neutral"})`,
											}}
										/>
										{kind} <span className="text-muted-foreground">{n}</span>
									</ToggleGroupItem>
								))}
								{/* Not "clear": the cascade's clear button is found by name.
								    These two carry testids because Playwright matches an
								    accessible name as a substring, and "tallybird" contains
								    "all" — every org row answers to that query too. */}
								<Button
									variant="link"
									size="xs"
									className="h-5 p-0 text-[11px] text-[var(--mark)]"
									data-testid="filter-all"
									onClick={() => setHidden(new Set())}
								>
									all
								</Button>
								<Button
									variant="link"
									size="xs"
									className="h-5 p-0 text-[11px] text-[var(--mark)]"
									data-testid="filter-none"
									onClick={() =>
										setHidden(new Set(kinds.map(([kind]) => kind)))
									}
								>
									none
								</Button>
							</ToggleGroup>
						)}
						<Timeline
							events={visible}
							selected={selected}
							chain={chain}
							onSelect={select}
							laneRef={laneRef}
							footer={
								// Always mounted, whatever it says: the observer attaches to
								// this node once and must not have it swapped out from
								// under it.
								<div
									className="lane-end"
									ref={sentinelRef}
									data-testid="lane-end"
								>
									{failed !== null ? (
										<>
											Older events did not load.{" "}
											<Button
												variant="link"
												size="xs"
												className="h-5 p-0 text-[11px] text-[var(--mark)]"
												onClick={() => {
													setFailed(null);
												}}
											>
												retry
											</Button>
										</>
									) : loading ? (
										"Loading older events…"
									) : more ? (
										"Scroll for older events"
									) : (
										"The beginning of the world"
									)}
								</div>
							}
						/>
					</CardContent>
				</Card>
			</div>
		</main>
	);
}
