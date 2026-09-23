"use client";

/**
 * /reports: the field report, live, and the reports published from it.
 *
 * The same sections as the first report (reports/day-1-in-prod), drawn by the
 * same components, over /report instead of a snapshot. Where that report had a
 * reader's prose, this one has the numbers in sentences and rule-based
 * findings (`live.ts`); where it had a reader's judgement, it links to the
 * published reports that carry one.
 *
 * Fetched in the browser (WEB-0005) and refreshed every minute while the tab
 * is visible. The API memoises the aggregates per tick, so an open tab costs
 * the database nothing between ticks.
 */
import type { FieldReport, TownMap } from "@jeve/contracts";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { JellyLoader } from "@/components/block/jelly-loader";
import { SiteFooter } from "@/components/SiteFooter";
import { fetchReport, fetchTownMap } from "@/lib/api";
import { REPORTS } from "@/reports";
import { BarChart, ColChart, Dumbbell, LineChart, type Series } from "./charts";
import { fmt, pct, usd } from "./format";
import {
	type AnswerRow,
	AnswerTables,
	Callout,
	CallsTable,
	Effects,
	EscLegend,
	Fig,
	Findings,
	Kicker,
	mainEffects,
	PeopleTable,
	ReportBar,
	SeriesToggle,
	Vital,
	WhoLegend,
} from "./parts";
import { TipProvider, TipRow } from "./tip";
import { TownReplay } from "./TownReplay";
import type { TownData } from "./town";
import {
	LIVE_CATS,
	liveFindings,
	liveTown,
	ORG_COLOR,
	ORG_SHORT,
	payrollStandings,
	spendWords,
	trailingMean,
	weakest,
} from "./live";

const REFRESH_MS = 60_000;

const NAV: [string, string][] = [
	["summary", "summary"],
	["published", "published"],
	["findings", "findings"],
	["run", "the run"],
	["economy", "economy"],
	["people", "people"],
	["model", "the model"],
	["outages", "outages"],
];

// Panel grey up to the accent, as the landing page's loader.
const LOADER = ["#262d36", "#37404d", "#55606e", "#77808f", "#8b96a5", "#7e6bb8", "#a78bfa", "#c4b5fd"];

const pad2 = (h: number) => String(h).padStart(2, "0");
const dayfmt = (d: number, tip?: boolean) => (tip ? `day ${d}` : `d${d}`);
const dollars = (v: number) => (Math.abs(v) >= 1000 ? `$${Math.round(v / 1000)}k` : `$${Math.round(v)}`);
const firstName = (name: string) => name.split(" ")[0] ?? name;

type Loaded = { report: FieldReport; map: TownMap; town: TownData };

export function LiveReport() {
	const [data, setData] = useState<Loaded | null>(null);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		let cancelled = false;
		let timer = 0;
		const load = async (map: TownMap | null) => {
			try {
				const [report, townMap] = await Promise.all([fetchReport(), map ? Promise.resolve(map) : fetchTownMap()]);
				if (cancelled) return;
				// The town is laid out once: its rates move slowly, and re-mounting
				// it would restart the replay under the reader every minute.
				setData((prev) => ({ report, map: townMap, town: prev?.town ?? liveTown(report, townMap) }));
				setError(null);
				schedule(townMap);
			} catch (reason) {
				if (cancelled) return;
				setError(reason instanceof Error ? reason.message : String(reason));
				schedule(map);
			}
		};
		const schedule = (map: TownMap | null) => {
			timer = window.setTimeout(function tick() {
				if (document.hidden) timer = window.setTimeout(tick, REFRESH_MS);
				else void load(map);
			}, REFRESH_MS);
		};
		void load(null);
		return () => {
			cancelled = true;
			window.clearTimeout(timer);
		};
	}, []);

	if (data === null) {
		return (
			<>
				<ReportBar sub="field report · live" links={[]} />
				<div className="page">
					{error === null ? (
						<div className="loading">
							<div className="relative h-28 w-28">
								<JellyLoader colors={LOADER} />
							</div>
							<p>Reading the world…</p>
						</div>
					) : (
						<div className="loading" data-testid="report-error">
							<p>The API is not reachable, so there is no live report to draw.</p>
							<pre>{error}</pre>
							<p>
								The published reports do not need it: <Published />
							</p>
						</div>
					)}
					<SiteFooter />
				</div>
			</>
		);
	}
	return <Report report={data.report} town={data.town} stale={error} />;
}

function Published() {
	return (
		<>
			{REPORTS.map((r, i) => (
				<span key={r.slug}>
					{i > 0 && ", "}
					<Link href={`/reports/${r.slug}`}>{r.title}</Link>
				</span>
			))}
		</>
	);
}

function Report({ report: r, town, stale }: { report: FieldReport; town: TownData; stale: string | null }) {
	const v = r.vitals;
	const [hidden, setHidden] = useState<Set<string>>(new Set());
	const findings = useMemo(() => liveFindings(r), [r]);
	const standings = payrollStandings(r);
	const weak = weakest(r);
	const staff = v.persons.staff ?? r.people.length;
	const gatedShare = v.decisions ? 1 - v.modelled / v.decisions : 0;
	const running = r.clock.status === "running" && !r.health.stale;
	const asOf = new Date(r.as_of);
	const asOfText = Number.isNaN(asOf.getTime())
		? r.as_of
		: `${asOf.toISOString().slice(0, 16).replace("T", " ")} UTC`;

	// The run.
	const cacheDays = r.cache_by_day;
	const hitRate = trailingMean(cacheDays.map((d) => (d.decisions ? 1 - d.new_calls / d.decisions : 0)));
	const calls = r.calls
		.filter((c) => c.calls > 0)
		.map((c) => ({ set: c.question_set, calls: c.calls, decisions: c.decisions - c.gated, usd: c.usd }));
	const tickCalls = r.calls.find((c) => c.question_set === "agent.tick")?.calls ?? 0;
	const allCalls = r.calls.reduce((a, c) => a + c.calls, 0);

	// The economy.
	const firms: Series[] = r.cash.series
		.filter((s) => s.org_id !== null)
		.map((s) => ({
			name: ORG_SHORT[s.org_id ?? ""] ?? s.name,
			color: ORG_COLOR[s.org_id ?? ""] ?? "--dim",
			values: s.values.map((c) => c / 100),
			hidden: hidden.has(ORG_SHORT[s.org_id ?? ""] ?? s.name),
		}));
	const households = r.cash.series.find((s) => s.org_id === null)?.values.map((c) => c / 100) ?? [];
	const days = (r.cash.series[0]?.values ?? []).map((_, i) => r.cash.first_day + i);
	const closing = firms.map((s) => ({ name: s.name, cash: s.values.at(-1) ?? 0 })).sort((a, b) => a.cash - b.cash);
	const weakMark =
		weak?.last_paid_day != null && weak.last_paid_day >= r.cash.first_day ? weak.last_paid_day - r.cash.first_day : null;
	const h = r.households;
	const c = r.collections;

	// The people.
	const office = r.office_at_cafe;
	const peak = office.reduce<(typeof office)[number] | null>((a, b) => (a === null || b.share > a.share ? b : a), null);
	const walk = r.cafe_by_hour.map((x) => (x.sales + x.walkouts ? x.walkouts / (x.sales + x.walkouts) : 0));
	const pw = walk.indexOf(Math.max(0, ...walk));
	const minds = r.mood_by_mind.map((m) => ({
		...m,
		label:
			m.mind === "ordinary"
				? "ordinary working day"
				: m.mind === "other"
					? "something else"
					: `${r.outages.find((o) => o.module_id === m.mind)?.name ?? m.mind} down`,
	}));
	const mindTotal = minds.reduce((a, m) => a + m.decisions, 0);
	const people = r.people.map((p) => ({
		id: p.id,
		name: p.name,
		org: p.org_id,
		role: p.role.replace(/_/g, " "),
		mood: p.mood ?? 0,
		cafe: p.cafe_share * 100,
		talk: p.talk_share * 100,
		raised: p.raised,
		soc: p.sociability,
		dil: p.diligence,
	}));

	// The model.
	const tables = r.answers as Record<string, AnswerRow[]>;
	const effects = Object.fromEntries(
		Object.entries(tables)
			.map(([q, rows]) => [q, mainEffects(rows)] as const)
			.filter(([, e]) => Object.keys(e).length > 0),
	);
	const effectOrder = Object.keys(effects).sort();

	// Outages.
	const outageRows = r.outages
		.filter((o) => o.incidents > 0)
		.map((o) => ({
			...o,
			esc: o.minutes_escalated === null ? null : Math.round(o.minutes_escalated),
			not: o.minutes_not_escalated === null ? null : Math.round(o.minutes_not_escalated),
		}));
	const receivers = r.people.filter((p) => p.received > 0).sort((a, b) => b.received - a.received);
	const k = r.knowledge;

	return (
		<TipProvider>
			<ReportBar sub={`field report · live · ${r.clock.run_id}`} links={NAV} />
			<div className="page">
				<TownReplay data={town} clock={`d${r.clock.day} replay`} booksId="economy">
					The simulation's own map (<code>world/map.py</code>), with all {staff} staff at their seats. The replay is
					rebuilt from this run's measured rates, not recorded frames: how often each person heads to the cafe follows
					their share of time there, the queue follows cafe arrivals by hour, and the speech bubbles use the real topic
					mix. Hover anyone, or click a building for its books.
				</TownReplay>

				<header id="summary" className="summary">
					<Kicker>Field report · live · run {r.clock.run_id}</Kicker>
					<h1>
						{fmt(v.sim_days)} days on one street, for {spendWords(v.spend_usd)}
					</h1>
					<p className="lede">
						What jeve's database has recorded so far: four firms, {fmt(staff)} staff,{" "}
						{fmt(v.persons.counterparty ?? 0)} counterparties, {fmt(v.events)} events and {fmt(v.decisions)} typed
						decisions. Every number on this page is recomputed from the running world, at most once a tick.
					</p>
					<div className="status" data-testid="report-status">
						<span>
							<b>d{r.clock.day}</b>
						</span>
						<span>tick {fmt(r.clock.tick_seq)}</span>
						<span>seq {fmt(r.seq)}</span>
						<span className={`badge ${running ? "b-good" : r.health.stale ? "b-bad" : "b-warn"}`}>
							● {r.health.stale ? "stale" : r.clock.status.replace(/_/g, " ")} · lag {Math.round(r.health.lag_s)} s
						</span>
						{r.model && <span className="badge b-mark">{r.model.replace(/^.*\//, "")}</span>}
						<span>
							as of {asOfText} · <i className="live-dot" /> live
						</span>
						{stale && <span className="badge b-warn">refresh failed; showing the last read</span>}
					</div>

					<div className="vitals" data-testid="vitals">
						<Vital n={fmt(v.sim_days)} unit="sim-days">
							since the run began; nights and Sundays are skipped
						</Vital>
						<Vital n={fmt(v.decisions)}>
							typed decisions: {pct(1 - gatedShare)} from a model, {pct(gatedShare)} settled free by a gate
						</Vital>
						<Vital n={`$${v.spend_usd.toFixed(2)}`}>
							priced per distinct call, about ${(v.spend_usd / Math.max(1, v.sim_days)).toFixed(4)} a sim-day
						</Vital>
						<Vital n={pct(v.cache_hit_rate)}>
							of modelled decisions served from cache: {fmt(v.distinct_calls)} distinct calls in all
						</Vital>
						{weak ? (
							<Vital n={`${weak.paid} / ${weak.due}`} alert={weak.paid / Math.max(1, weak.due) < 0.8}>
								payroll runs {ORG_SHORT[weak.org_id] ?? weak.name} has met
								{weak.last_paid_day === null ? ", and none yet" : `, and none since day ${weak.last_paid_day}`}
							</Vital>
						) : (
							<Vital n={`${standings.length} / ${standings.length}`}>firms meeting payroll on every run so far</Vital>
						)}
						<Vital n={v.incidents ? pct(v.incidents_escalated / v.incidents) : "—"}>
							{v.incidents
								? `of ${fmt(v.incidents)} outages escalated in person, ${v.escalations ? pct(v.escalations_in_cafe / v.escalations) : "none"} of those over coffee`
								: "no outages yet"}
						</Vital>
					</div>
				</header>

				<section id="published">
					<Kicker>Published</Kicker>
					<h2>Reports, frozen</h2>
					<p className="sub">
						Read against a snapshot and written up by hand: the numbers as they stood, and what someone made of them.
					</p>
					<div className="pubs">
						{REPORTS.map((p) => (
							<Link key={p.slug} href={`/reports/${p.slug}`} className="pub" data-testid={`report-${p.slug}`}>
								<div className="tags">
									<span className="badge b-mark">{p.date}</span>
									<span className="cat">run {p.run}</span>
								</div>
								<h3>{p.title}</h3>
								<p>
									<b>{p.headline}.</b> {p.summary}
								</p>
								<div className="evd">{p.scope} · read it →</div>
							</Link>
						))}
					</div>
				</section>

				<section id="findings">
					<Kicker>What the numbers say</Kicker>
					<h2>{findings.length === 1 ? "One finding" : `${fmt(findings.length)} findings`}, recomputed</h2>
					<p className="sub">
						Each is a rule over the live aggregates with a threshold standing in for a reader's judgement; the last line
						of every card is where the number comes from.
					</p>
					<Findings items={findings} cats={LIVE_CATS} storageKey="jeve-live-f" />
				</section>

				<section id="run">
					<Kicker>The run</Kicker>
					<h2>What the model was asked, and what it cost</h2>
					<p className="sub">
						{fmt(v.modelled)} modelled decisions over {fmt(v.sim_days)} sim-days, answered by {fmt(v.distinct_calls)}{" "}
						distinct calls{r.model ? ` to ${r.model}` : ""}.
					</p>
					<div className="stack">
						<Fig
							title="Cache hit rate by sim-day"
							legend="7-day mean"
							caption="Share of modelled decisions answered by a call made before. It climbs as the cache fills and flattens where every new day brings contexts the town has not seen."
						>
							{cacheDays.length ? (
								<LineChart
									series={[{ name: "hit rate", color: "--mark", values: hitRate }]}
									xs={cacheDays.map((d) => d.day)}
									yMin={0}
									yTicks={[0, 0.25, 0.5, 0.75, 1]}
									area
									h={250}
									yfmt={(x) => `${Math.round(x * 100)}%`}
									xfmt={dayfmt}
									aria="Cache hit rate by sim-day"
								/>
							) : (
								<Empty>No model has answered a decision yet: this world runs on rules.</Empty>
							)}
						</Fig>
						<Fig
							title="Where the calls went"
							legend={`${calls.length} question sets`}
							caption={
								allCalls ? (
									<>
										<code>agent.tick</code> accounts for {pct(tickCalls / allCalls, 1)} of distinct calls: its prompt
										carries who is in the room, so every new crowd is a new call.
									</>
								) : undefined
							}
						>
							{calls.length ? <CallsTable rows={calls} /> : <Empty>No calls yet.</Empty>}
						</Fig>
					</div>
				</section>

				<section id="economy">
					<Kicker>The economy</Kicker>
					<h2>Four firms' cash, and where the wages go</h2>
					<p className="sub">
						Cash on hand at the end of each sim-day, from {fmt(v.ledger_entries)} ledger entries that sum to{" "}
						{v.ledger_imbalance_cents === 0 ? "exactly zero" : usd(v.ledger_imbalance_cents)}. Click a firm in the
						legend to hide it.
					</p>
					<Fig
						title="Cash by firm"
						legend={<SeriesToggle series={firms} hidden={hidden} onChange={setHidden} />}
						caption={
							closing.length
								? `${closing[0]?.name} holds the least, ${dollars(closing[0]?.cash ?? 0)}; ${closing.at(-1)?.name} the most, ${dollars(closing.at(-1)?.cash ?? 0)}.${weak ? ` ${ORG_SHORT[weak.org_id] ?? weak.name} has met ${weak.paid} of ${weak.due} payroll runs.` : ""}`
								: undefined
						}
					>
						<LineChart
							series={firms}
							xs={days}
							endLabels
							h={330}
							yfmt={dollars}
							xfmt={dayfmt}
							aria="Cash by firm, by sim-day"
							vlines={weakMark === null ? [] : [weakMark]}
							notes={
								weakMark === null || !weak
									? []
									: [
											{
												i: weakMark,
												v: firms.find((s) => s.name === ORG_SHORT[weak.org_id])?.values[weakMark] ?? 0,
												text: `last payroll · d${weak.last_paid_day}`,
											},
										]
							}
						/>
					</Fig>
					<div className="grid2 mt">
						<Fig title="Payroll by firm" caption="Runs paid and held, against the most any firm has paid.">
							<div className="tbl">
								<table data-testid="payroll">
									<thead>
										<tr>
											<th>firm</th>
											<th className="n">paid</th>
											<th className="n">held</th>
											<th className="n">last paid</th>
											<th className="n">warnings</th>
										</tr>
									</thead>
									<tbody>
										{standings.map((p) => (
											<tr key={p.org_id}>
												<td>
													<div className="who">
														<b>
															<i
																className="dot who-dot"
																style={{ background: `var(${ORG_COLOR[p.org_id] ?? "--dim"})` }}
															/>
															{ORG_SHORT[p.org_id] ?? p.name}
														</b>
													</div>
												</td>
												<td className={p.behind ? "n bad" : "n"}>
													{p.paid} / {p.due}
												</td>
												<td className="n">{p.held}</td>
												<td className="n">{p.last_paid_day === null ? "—" : `d${p.last_paid_day}`}</td>
												<td className="n">{fmt(p.insolvency_warnings)}</td>
											</tr>
										))}
									</tbody>
								</table>
							</div>
						</Fig>
						<Fig
							title="Household cash"
							caption={
								h.wages_cents
									? `Of ${usd(h.wages_cents)} paid in wages, ${usd(h.spending_cents)} (${pct(h.spending_cents / h.wages_cents, 1)}) came back as spending.`
									: "No wages paid yet."
							}
						>
							<LineChart
								series={[{ name: "household cash", color: "--sand", values: households }]}
								xs={days}
								area
								h={260}
								mt={20}
								yfmt={dollars}
								xfmt={dayfmt}
								aria="Household cash, by sim-day"
							/>
						</Fig>
					</div>
					<Callout title={c.overdue === 0 ? "Collections work." : "Collections lag."}>
						{fmt(c.paid)} invoices were paid, {c.mean_days_late?.toFixed(2) ?? "0"} days late on average and never more
						than {c.max_days_late ?? 0}. {fmt(c.open)} are open, {fmt(c.overdue)} of them past due, and{" "}
						{c.written_off ? `${fmt(c.written_off)} were written off` : "nothing was written off"}.
					</Callout>
				</section>

				<section id="people">
					<Kicker>The people</Kicker>
					<h2>How the day is spent</h2>
					<p className="sub">
						{fmt(r.people.reduce((a, p) => a + p.decisions, 0))} <code>agent.tick</code> decisions: every staff member, every open tick, asked where to go, what mood
						they're in, and whether to talk.
					</p>
					<div className="grid2">
						<Fig
							title="Office staff at the cafe"
							legend="share of their time, by hour"
							caption={
								peak
									? `Peaks at ${pad2(peak.hour)}:00, when ${pct(peak.share)} of office time is spent at the cafe. Walked from every move staff made.`
									: undefined
							}
						>
							{office.length ? (
								<ColChart
									cats={office.map((x) => pad2(x.hour))}
									values={office.map((x) => x.share)}
									color="--tr"
									h={250}
									yfmt={(x) => `${Math.round(x * 100)}%`}
									aria="Share of office staff at the cafe by hour"
									notes={peak ? [{ i: office.indexOf(peak), text: `peak · ${pct(peak.share)}` }] : []}
									tipf={(i) => (
										<>
											<b>{pad2(office[i]?.hour ?? 0)}:00</b>
											<TipRow label="at the cafe">{pct(office[i]?.share ?? 0, 1)}</TipRow>
										</>
									)}
								/>
							) : (
								<Empty>Nobody has moved yet.</Empty>
							)}
						</Fig>
						<Fig
							title="Cafe walkouts"
							legend="share of arrivals, by hour"
							caption="Walkouts track the line: an hour nobody queues in reads zero, because those arrivals are settled by the no-line gate."
						>
							{r.cafe_by_hour.length ? (
								<ColChart
									cats={r.cafe_by_hour.map((x) => pad2(x.hour))}
									values={walk}
									color="--tr"
									h={250}
									yfmt={(x) => `${Math.round(x * 100)}%`}
									aria="Cafe walkout rate by hour"
									notes={pw >= 0 && (walk[pw] ?? 0) > 0 ? [{ i: pw, text: `busiest · ${pct(walk[pw] ?? 0)}` }] : []}
									tipf={(i) => (
										<>
											<b>{pad2(r.cafe_by_hour[i]?.hour ?? 0)}:00</b>
											<TipRow label="walkout rate">{pct(walk[i] ?? 0, 1)}</TipRow>
											<TipRow label="sales">{fmt(r.cafe_by_hour[i]?.sales ?? 0)}</TipRow>
											<TipRow label="walkouts">{fmt(r.cafe_by_hour[i]?.walkouts ?? 0)}</TipRow>
										</>
									)}
								/>
							) : (
								<Empty>The cafe has not opened yet.</Empty>
							)}
						</Fig>
					</div>
					{minds.length > 0 && (
						<Fig
							title="Mood by what's on their mind"
							legend="mean on a 0–3 scale"
							className="mt"
							caption={
								<>
									What the prompt's <code>on_their_mind</code> said, across {fmt(mindTotal)} modelled{" "}
									<code>agent.tick</code> calls: {minds.length} values,{" "}
									{pct((minds.find((m) => m.mind === "ordinary")?.decisions ?? 0) / Math.max(1, mindTotal))} of them an
									ordinary working day.
								</>
							}
						>
							<BarChart
								cats={minds.map((m) => m.label)}
								values={minds.map((m) => m.mood)}
								max={3}
								color="--mark"
								fmt={(x) => `${x.toFixed(2)} / 3`}
								aria="Mean mood by what is on their mind"
								tipf={(i) => (
									<>
										<b>{minds[i]?.label}</b>
										<TipRow label="mean mood">{minds[i]?.mood.toFixed(2)}</TipRow>
										<TipRow label="decisions">{fmt(minds[i]?.decisions ?? 0)}</TipRow>
									</>
								)}
							/>
						</Fig>
					)}
					<Fig
						title={`All ${fmt(people.length)} staff`}
						legend="click a column to sort"
						className="mt"
						caption="Mood is the mean chosen on every tick; the cafe share is time on the map spent there; stops to talk is the share of ticks that asked for an encounter."
					>
						<PeopleTable rows={people} />
					</Fig>
				</section>

				<section id="model">
					<Kicker>What moves the model</Kicker>
					<h2>Which inputs swing the answer</h2>
					<p className="sub">
						For each question set, the widest swing in the deciding probability as one input changes, averaged over the
						rest (main-effect range, 0–1), over the distinct calls actually made. Violet inputs describe who the person
						is; sand ones describe their situation.
					</p>
					{effectOrder.length ? (
						<>
							<Fig caption="Computed from the answer tables below, so it moves as the cache fills. Not a controlled design: read it as a ranking.">
								<WhoLegend />
								<Effects effects={effects} order={effectOrder} />
							</Fig>
							<AnswerTables tables={tables} initial="payment.timing" storageKey="jeve-live-lt" />
						</>
					) : (
						<Fig>
							<Empty>No model has answered a decision yet: this world runs on rules.</Empty>
						</Fig>
					)}
				</section>

				<section id="outages">
					<Kicker>Outages and escalation</Kicker>
					<h2>Where outages get fixed</h2>
					<p className="sub">
						{fmt(v.incidents)} incidents, {fmt(r.outages.reduce((a, o) => a + o.tickets, 0))} tickets,{" "}
						{fmt(v.escalations)} escalations
						{v.escalations ? `, ${pct(v.escalations_in_cafe / v.escalations)} of them in the cafe` : ""}.
					</p>
					<div className="grid2">
						<Fig
							title="Outage length, minutes"
							legend={<EscLegend />}
							caption="Mean length of each module's outages, split by whether someone escalated them in person. Un-escalated means include outages that ran over a skipped night."
						>
							{outageRows.length ? (
								<Dumbbell
									rows={outageRows}
									tipf={(i) => {
										const o = outageRows[i];
										if (!o) return null;
										return (
											<>
												<b>{o.name}</b>
												<TipRow label="incidents">{o.incidents}</TipRow>
												<TipRow label="escalated">
													{o.escalated} ({pct(o.escalated / o.incidents)})
												</TipRow>
												<TipRow label="minutes to escalate">
													{o.minutes_to_escalate === null ? "—" : Math.round(o.minutes_to_escalate)}
												</TipRow>
												<TipRow label="mean length, escalated">{o.esc === null ? "—" : `${o.esc} min`}</TipRow>
												<TipRow label="mean length, not">{o.not === null ? "—" : `${o.not} min`}</TipRow>
												<TipRow label="tickets">{o.tickets}</TipRow>
											</>
										);
									}}
								/>
							) : (
								<Empty>Nothing has gone down yet.</Empty>
							)}
						</Fig>
						<Fig
							title="Who got escalated to"
							legend="escalations received"
							caption={
								receivers[0]
									? `${firstName(receivers[0].name)} (${receivers[0].role.replace(/_/g, " ")}, ${pct(receivers[0].cafe_share)} of their time at the cafe) has taken the most.`
									: undefined
							}
						>
							{receivers.length ? (
								<BarChart
									cats={receivers.map((p) => `${firstName(p.name)} · ${p.role.replace(/_/g, " ")}`)}
									values={receivers.map((p) => p.received)}
									color="--tb"
									rowH={28}
									fmt={(x) => String(x)}
									aria="Escalations received, by person"
									tipf={(i) => (
										<>
											<b>{receivers[i]?.name}</b>
											<TipRow label="escalations received">{receivers[i]?.received}</TipRow>
											<TipRow label="time at the cafe">{pct(receivers[i]?.cafe_share ?? 0, 1)}</TipRow>
										</>
									)}
								/>
							) : (
								<Empty>No one has been escalated to yet.</Empty>
							)}
						</Fig>
					</div>
					<Callout title={k.relayed === 0 ? "Conversation moves no information." : "What talk carries."}>
						{fmt(k.encounters)} encounters so far; {fmt(k.relayed)} of {fmt(k.first_hand + k.relayed)} knowledge rows
						were passed on rather than seen first-hand.
					</Callout>
					<SiteFooter>
						<span>jeve · run {r.clock.run_id} · live</span>
						<span>as of {asOfText}</span>
					</SiteFooter>
				</section>
			</div>
		</TipProvider>
	);
}

function Empty({ children }: { children: React.ReactNode }) {
	return <div className="empty">{children}</div>;
}
