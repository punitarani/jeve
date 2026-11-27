"use client";

/**
 * "The first 16,000 days": the third field report, as published on 2026-11-27.
 *
 * Frozen on purpose, like Day 1 and Day 3. It reads the production run from
 * its first tick to the last complete 28-day sim-month inside its first
 * 16,000 days: months 0-570, sim days 0-15,987, tick_seq below 602,977. The
 * numbers are the production database read between 07:01 and 07:45 UTC that
 * morning through a read-only role, PlanetScale's query insights for the
 * seven days before, and timed requests to the public API. `data.json` holds
 * the monthly series; the smaller tables are constants below, each from the
 * queries listed under Method.
 */
import { BarChart, LineChart, type Series } from "@/components/report/charts";
import { dollars, fmt } from "@/components/report/format";
import {
	Callout,
	type Defect,
	Defects,
	Fig,
	Kicker,
	ReportBar,
	Say,
	SeriesToggle,
	Vital,
} from "@/components/report/parts";
import { TipProvider, TipRow } from "@/components/report/tip";
import { TownReplay } from "@/components/report/TownReplay";
import type { TownData } from "@/components/report/town";
import { SiteFooter } from "@/components/SiteFooter";
import { useMemo, useState } from "react";
import raw from "./data.json";

type Staff = { id: string; org: string; role: string; name: string; seat: [number, number]; spot?: [number, number]; path: [number, number][] };
type Firm = "halloran" | "ledgerline" | "thirdrail";
type Data = {
	months: number;
	cash: Record<"tallybird" | Firm | "households", number[]>;
	rev: Record<Firm, number[]>;
	exp: Record<Firm, number[]>;
	dec: { n: number[]; rules: number[]; tick: number[]; round: number[] };
	novel: { tick: number[]; round: number[]; other: number[] };
	hit: (number | null)[];
	wall_h: number[];
	mood: Record<Firm, (number | null)[]>;
	topic: Record<"money" | "work" | "small_talk", number[]>;
	ev: Record<"encounter" | "episode" | "sale" | "disputed" | "warning" | "missed", number[]>;
	friction: number[];
	logged: (number | null)[];
	velocity: (number | null)[];
	halloran: { w0: number; cash: number[]; loan: number[] };
	town: {
		kinds: Record<string, string>;
		tiles: string[];
		queue: [number, number][];
		staff: Staff[];
		people: Record<string, { cafe: number; talk: number; mood: number }>;
		cafeShare: Record<string, number>;
		arrivals: Record<string, number>;
		topics: [string, number][];
	};
};
const D = raw as unknown as Data;
const N = D.months;
/** Month m holds sim days 28m to 28m+27; a monthly balance is read as of the day it ends. */
const END = Array.from({ length: N }, (_, m) => 28 * (m + 1));
const dayx = (d: number, tip?: boolean) => (tip ? `day ${fmt(d)}` : `d${fmt(d)}`);
const num = (xs: (number | null)[]) => xs.map((x) => x ?? 0);
/** A trailing mean over `w` months, so a monthly series reads as a trend. */
const smooth = (xs: (number | null)[], w: number) =>
	xs.map((_, i) => {
		const win = xs.slice(Math.max(0, i - w + 1), i + 1).filter((x): x is number => x !== null);
		return win.length ? win.reduce((a, b) => a + b, 0) / win.length : 0;
	});
/** Months 19 onward: the three firms that outlived Tallybird. */
const AFTER = 19;
/** The era boundaries, as month indices: Tallybird fails, Halloran's first warning, its loan cleared. */
const ERA_LINES = [19, 272, 407];
const pct = (v: number, d = 0) => `${(v * 100).toFixed(d)}%`;
/** Dollars that read millions as millions: $1.43M, not $1431k. */
const money = (v: number) => (Math.abs(v) >= 1e6 ? `$${(v / 1e6).toFixed(v >= 1e7 ? 0 : 2)}M` : dollars(v));

const NAV: [string, string][] = [
	["summary", "summary"],
	["eras", "four eras"],
	["halloran", "halloran"],
	["economy", "economy"],
	["people", "people"],
	["model", "the model"],
	["run", "the run"],
	["novelty", "what's new"],
	["defects", "defects"],
	["next", "next"],
];

// -- the eras: cut by what happened in the world, not by deploys ------------------

const ERAS = [
	{
		id: "E1",
		name: "Four firms",
		days: "d0 → d532",
		body: "Day 1 and Day 3's world: three deploys, then Tallybird fails at d533 with four paydays missed.",
		n: "19 months · 2.7 wall days · 460k decisions",
	},
	{
		id: "E2",
		name: "Three firms settle",
		days: "d532 → d7,616",
		body: "Nobody is in danger. Halloran spends about $420 a month more than it earns, and its cash runs from $132k down to $14k.",
		n: "253 months · 26.1 wall days · 2.54M decisions",
	},
	{
		id: "E3",
		name: "Halloran's crisis",
		days: "d7,616 → d11,396",
		body: "112 warnings, one loan, 47 missed paydays, four people out and four hired. The loan is cleared at d11,403.",
		n: "135 months · 16.3 wall days · 1.36M decisions",
		alert: "47 paydays missed",
	},
	{
		id: "E4",
		name: "Steady state",
		days: "d11,396 → d15,988",
		body: "No warning and no missed payday. Halloran earns $8.2k a month more than it spends; the model meets 22 new situations a month.",
		n: "164 months · 21.4 wall days · 1.64M decisions",
	},
];

/** Per era, from the decision, model-call and ledger reads (Method). Cost is new calls × each kind's mean cost per call. */
const ERA_COST = [
	{ e: "E1 · four firms", days: 532, wall: 2.7, dec: 460365, gated: 0.122, calls: 45416, usd: 1.874, hit: 0.8876 },
	{ e: "E2 · settle", days: 7084, wall: 26.1, dec: 2542339, gated: 0.328, calls: 18506, usd: 0.669, hit: 0.9892 },
	{ e: "E3 · crisis", days: 3780, wall: 16.3, dec: 1361042, gated: 0.327, calls: 5846, usd: 0.217, hit: 0.9936 },
	{ e: "E4 · steady", days: 4592, wall: 21.4, dec: 1644559, gated: 0.329, calls: 3612, usd: 0.124, hit: 0.9967 },
];

// -- Halloran, from the event log ---------------------------------------------------

const TIMELINE: { d: string; t: string; k?: "bad" | "mark" }[] = [
	{ d: "d7,620", t: "First insolvency warning: thin reserves. The true fact that Halloran is in trouble is born the same day; 17 people come to hold it." },
	{ d: "d7,921", t: "Maeve Halloran answers ‘borrow’ at her review. The bank lends $62,215, six weeks of running costs.", k: "mark" },
	{ d: "d9,552", t: "First payroll held for want of cash. Wages are $9,100 a week.", k: "bad" },
	{ d: "d9,660", t: "Two paydays behind. Nadia Farrow, junior associate, decides to leave.", k: "bad" },
	{ d: "d9,667", t: "A week later Maeve fills the desk with Casey Ibrahim. Paydays keep being missed." },
	{ d: "d10,248", t: "Priya Raghunathan and Owen Castellanos leave on the same payday.", k: "bad" },
	{ d: "d10,255", t: "Quinn Santos is hired as paralegal; Quinn Silva as office manager on d10,311." },
	{ d: "d10,794", t: "The low point: $91 in the bank at the week's end." },
	{ d: "d10,836", t: "Casey Ibrahim leaves, unpaid, 1,169 days after starting.", k: "bad" },
	{ d: "d10,871", t: "Emerson Quispe is hired as junior associate." },
	{ d: "d10,917", t: "The last missed payday: 47 in 1,365 days, never four in a row." },
	{ d: "d11,403", t: "The loan is cleared, after $75,268 of interest on $62,215.", k: "mark" },
];

/** Logged share of minutes worked, from `timesheets` (d511–d15,987), with each person's diligence trait. */
const LOGGERS: { name: string; role: string; fate: string; share: number; diligence: number; unbilled: number; left: boolean }[] = [
	{ name: "Emerson Quispe", role: "junior associate", fate: "hired d10,871", share: 0.9501, diligence: 0.691, unbilled: 126499, left: false },
	{ name: "Julian Pike", role: "senior associate", fate: "since d0", share: 0.9465, diligence: 0.743, unbilled: 557074, left: false },
	{ name: "Maeve Halloran", role: "partner", fate: "since d0", share: 0.8268, diligence: 0.599, unbilled: 1972416, left: false },
	{ name: "Quinn Santos", role: "paralegal", fate: "hired d10,255", share: 0.741, diligence: 0.589, unbilled: 357332, left: false },
	{ name: "Nadia Farrow", role: "junior associate", fate: "left d9,660", share: 0.4244, diligence: 0.397, unbilled: 2605122, left: true },
	{ name: "Owen Castellanos", role: "paralegal", fate: "left d10,248", share: 0.4227, diligence: 0.403, unbilled: 1351722, left: true },
	{ name: "Casey Ibrahim", role: "junior associate", fate: "d9,667–d10,836", share: 0.4131, diligence: 0.359, unbilled: 338235, left: true },
];

// -- the model --------------------------------------------------------------------------

/** Share of each question set's most common answer, over the whole window (decisions.chosen). */
const ONE_ANSWER: { set: string; n: number; top: string; share: number }[] = [
	{ set: "dispute.resolution", n: 7072, top: "stand firm", share: 1 },
	{ set: "supplier.order", n: 2211, top: "the usual", share: 1 },
	{ set: "cover.shift", n: 248, top: "cover it", share: 1 },
	{ set: "founder.review · LL + TR", n: 1106, top: "hold course", share: 1 },
	{ set: "close.signoff", n: 1480, top: "readiness 2", share: 0.96 },
	{ set: "catering.order", n: 9270, top: "none", share: 0.907 },
	{ set: "founder.review · Halloran", n: 603, top: "hold course", share: 0.726 },
	{ set: "chase.invoice", n: 2130, top: "don't chase", share: 0.664 },
	{ set: "catering.accept", n: 1248, top: "accept", share: 0.58 },
	{ set: "invoice.dispute", n: 15056, top: "don't dispute", share: 0.557 },
	{ set: "time.log", n: 43966, top: "log it", share: 0.513 },
	{ set: "payment.timing", n: 36163, top: "defer", share: 0.51 },
];

/** Tier 1 in shadow on dispute.resolution: agreements / escalations, by the issuing firm and century of months. */
const TIER1_DISPUTES: { era: string; m: number; hp: [number, number]; ll: [number, number]; tr: [number, number] }[] = [
	{ era: "months 0–99", m: 50, hp: [405, 456], ll: [536, 536], tr: [21, 21] },
	{ era: "100–199", m: 150, hp: [20, 591], ll: [638, 638], tr: [23, 23] },
	{ era: "200–299", m: 250, hp: [0, 569], ll: [618, 618], tr: [21, 21] },
	{ era: "300–399", m: 350, hp: [18, 602], ll: [661, 661], tr: [21, 21] },
	{ era: "400–499", m: 450, hp: [569, 591], ll: [656, 656], tr: [27, 27] },
	{ era: "500–570", m: 535, hp: [443, 443], ll: [462, 462], tr: [17, 17] },
];

const DEFECTS: Defect[] = [
	{
		s: "critical",
		t: "One count takes two-thirds of the database",
		b: "Tier 1's daily allowance counts yesterday's decisions with a sim_time range on a table that has no sim_time index, so every call reads all of it: 5.76 million rows, a median of 21.6 s. In the seven days to 07:00 UTC on 27 November it ran 1,116 times and took 66.6% of all database time. It grows with the run, which AGENTS.md forbids on a hot path, and the query-plan test does not cover it.",
		loc: "py/src/jeve/decide/escalation.py:250 room() · PlanetScale insights, 7 days",
	},
	{
		s: "high",
		t: "The live report and the economics page no longer answer",
		b: "GET /report gave no answer within 300 s three times, the last with this report's own reads finished; GET /economics once; even GET /state took 21 s. The report's queries count and sum whole tables (count(DISTINCT model_call) over 5.9M decisions, every ledger entry), and insights puts that statement at a 91 s median. Day 3 measured 19–40 s.",
		loc: "py/src/jeve/api/report.py:111 · py/src/jeve/api/app.py:502 · timed 07:11–07:30 UTC",
	},
	{
		s: "high",
		t: "‘Borrow’ is offered when it cannot be granted",
		b: "Maeve Halloran answered ‘borrow’ 93 times. The first got a loan; the other 92 did nothing, because borrow() refuses a firm that already owes the bank. The review still offers the option, and nothing is recorded when it is refused.",
		loc: "py/src/jeve/world/economy.py:517 borrow() · founder.review 93 × borrow, 1 loan.taken",
	},
	{
		s: "high",
		t: "A bridging loan that took 3,482 days to repay",
		b: "Repayment starts only once cash exceeds twelve weeks of outgoings, which a firm that needed a loan rarely reaches. Halloran paid 0.25% a week on $62,215 for nearly ten sim-years: $75,268 of interest, 121% of what it borrowed, through the worst of its crisis.",
		loc: "py/src/jeve/world/economy.py:465 loans_week · REPAY_ABOVE_WEEKS = 12",
	},
	{
		s: "high",
		t: "Dispute resolution is still a rule wearing a question",
		b: "Day 3 flagged ‘stand firm’ at 103 of 103. It is now 7,072 of 7,072, across every firm, size and runway. WORLD-0011's reversal condition has been met for 15,000 sim-days.",
		loc: "dispute.resolution · 7,072 decisions, 1 distinct answer",
	},
	{
		s: "note",
		t: "Profit has nowhere to go",
		b: "Ledgerline adds about $7.3k a month and never spends it: $4.31M by d15,988, 70% of all the cash in town. No rule pays an owner, invests or competes, and its head has chosen ‘hold course’ 553 times out of 553. Money velocity falls from 6.3% of the town's cash a week to 0.8%, so the detector fires every month after the 50th, by more each time.",
		loc: "py/src/jeve/world/economy.py REVIEW_CHOICES · api/detectors.py MONEY_VELOCITY = 0.05",
	},
	{
		s: "note",
		t: "Each cash read folds an account's whole history",
		b: "cash_of() sums every ledger entry an account has ever had. Third Rail's cash account holds 2.75M entries. In seven days it ran 13,639 times at 527k rows a call: 5.8% of database time, and growing with every coffee.",
		loc: "py/src/jeve/world/engine.py:446 cash_of · LLM-0010 solved the same shape for spend",
	},
	{
		s: "note",
		t: "The town has had no software vendor for 15,455 days",
		b: "Day 3's first recommendation is still open. Tallybird's 100 subscribers have been idle since d533, its $44,489 sits untouched, and the outage, ticket and churn loops have not run once since.",
		loc: "incidents: last d527 · subscriptions active: 0 of 105",
	},
	{
		s: "note",
		t: "Seven long stops left no reason behind",
		b: "Seven sim-months took 22–40 wall hours instead of the usual 2.3. sim_meta keeps only the current status, so the database cannot say whether the daemon was waiting on the model, the budget or the database. They cost 10 of the run's 66 wall days.",
		loc: "sim_meta (one row) · months 93, 316, 385, 443, 484, 520, 551",
	},
];

function townData(): TownData {
	const T = D.town;
	const nums = (r: Record<string, number>) => Object.fromEntries(Object.entries(r).map(([k, v]) => [+k, v]));
	return {
		tiles: T.tiles.map((row) => [...row].map((c) => T.kinds[c] ?? "grass")),
		cast: T.staff.map((s) => ({ ...s, org_id: s.org })),
		queue: T.queue,
		people: T.people,
		cafeShare: nums(T.cafeShare),
		arrivals: nums(T.arrivals),
		topics: T.topics,
		buildings: [
			{ org_id: "tallybird", zone: "software_office", name: "Tallybird Software", x0: 2, y0: 2, x1: 15, y1: 10, cash: D.cash.tallybird[N - 1] ?? 0, flag: "failed d533", note: "failed d533 · untouched since d546" },
			{ org_id: "halloran", zone: "law_office", name: "Halloran & Pike LLP", x0: 24, y0: 2, x1: 37, y1: 10, cash: D.cash.halloran[N - 1] ?? 0, note: "47 paydays missed d9,552–d10,917 · recovered" },
			{ org_id: "ledgerline", zone: "accounting_office", name: "Ledgerline Accounting", x0: 2, y0: 17, x1: 15, y1: 25, cash: D.cash.ledgerline[N - 1] ?? 0, note: "70% of the town's cash" },
			{ org_id: "thirdrail", zone: "cafe", name: "Third Rail Cafe", x0: 24, y0: 17, x1: 37, y1: 25, cash: D.cash.thirdrail[N - 1] ?? 0 },
		],
		outage: null,
		day: "d15,988 replay",
		cashLabel: "cash at d15,988",
	};
}

const FIRMS: ["tallybird" | Firm, string, string][] = [
	["tallybird", "Tallybird", "--tb"],
	["halloran", "Halloran & Pike", "--hp"],
	["ledgerline", "Ledgerline", "--ll"],
	["thirdrail", "Third Rail", "--tr"],
];

const pow10 = (v: number) => {
	const x = 10 ** v;
	return x >= 1000 ? `${Math.round(x / 1000)}k` : fmt(x);
};

export function First16000Days() {
	const town = useMemo(townData, []);
	const [hidden, setHidden] = useState<Set<string>>(new Set());

	const cashSeries: Series[] = FIRMS.map(([k, name, color]) => ({ name, color, values: D.cash[k], hidden: hidden.has(name) }));

	const after = useMemo(() => {
		const xs = END.slice(AFTER);
		const cut = (v: (number | null)[]) => num(v.slice(AFTER));
		const idx = (m: number) => m - AFTER;
		return { xs, cut, idx, lines: ERA_LINES.filter((m) => m > AFTER).map(idx) };
	}, []);

	const novelty = useMemo(() => {
		const lg = (xs: number[]) => smooth(xs, 6).map((v) => Math.log10(Math.max(1, v)));
		return { tick: lg(D.novel.tick), round: lg(D.novel.round), other: lg(D.novel.other) };
	}, []);

	const hal = D.halloran;
	const halDays = hal.cash.map((_, i) => (hal.w0 + i) * 7);
	const halAt = (day: number) => Math.round(day / 7) - hal.w0;

	return (
		<TipProvider>
			<ReportBar sub="field report · the first 16,000 days · golden-20260920" links={NAV} />
			<div className="page">
				<TownReplay data={town} clock="d15,988 replay" booksId="economy">
					The street at d15,988, with the 16 people still working on it. Three of Halloran's five desks hold people hired
					during its crisis; Tallybird's office has been empty since d533. The replay is rebuilt from the last 13
					sim-months: where each person's <code>agent.tick</code> answers sent them, cafe arrivals by hour, and what
					conversations were about. Hover anyone, or click a building for its books.
				</TownReplay>

				<header id="summary" className="summary">
					<Kicker>Field report · the first 16,000 days · production run golden-20260920</Kicker>
					<h1>Sixteen thousand days, one near-failure, and a cure nobody chose.</h1>
					<p className="lede">
						Day 3 ended at d742 with three firms left. The world has run on since, unattended and on the same code since
						d761. This report reads it from the first tick to the last complete sim-month inside its first 16,000 days:
						15,988 sim-days, 571 months of 28 days, 66 wall days and six million typed decisions, straight from the
						production database.
					</p>
					<div className="status">
						<span>
							<b>d0 → d15,988</b>
						</span>
						<span>571 months</span>
						<span>tick 602,976</span>
						<span>seq 1 → 4,310,078</span>
						<span className="badge b-good">● running · lag 0 s · no error</span>
						<span className="badge b-mark">jev-1.13-20260917</span>
						<span>engine 45f7bb4</span>
						<span>snapshot 2026-11-27 07:03 UTC · read-only</span>
					</div>

					<div className="vitals">
						<Vital n="15,988" unit="sim-days">
							571 sim-months in 66.4 wall days, with no code change since d761
						</Vital>
						<Vital n="6.0M">typed decisions, 31% settled free by a gate; 73,376 model calls</Vital>
						<Vital n="$2.89">for every model call the run has made. The last 4,592 sim-days cost 12 cents.</Vital>
						<Vital n="99.7%">of Jev's decisions answered from the cache in the last era: 22 new situations a month</Vital>
						<Vital n="47" unit="paydays" alert>
							missed by Halloran between d9,552 and d10,917. Four people left, four were hired.
						</Vital>
						<Vital n="67%" alert>
							of production database time spent on one unindexed count
						</Vital>
					</div>

					<Say by="the short version">
						For fifteen thousand days almost nothing changes: the same three firms, the same moods, 4,790 coffees a month.
						The exception is Halloran &amp; Pike. It lost about $420 a month for 250 months because two of its staff
						logged under half the hours they worked. A loan bought time and cost more than it lent. 47 missed paydays
						drove four people out, and two of the people hired in their place happen to log 74% and 95% of theirs.{" "}
						<em>Revenue rose 23%, and a firm that had $91 in the bank on d10,794 holds $1.43M at d15,988.</em> Nobody
						decided that: hiring asks whether to fill a desk, never whom. Meanwhile the model meets fewer new situations
						every month, and the database spends two-thirds of its time on one count.
					</Say>
				</header>

				<section id="eras">
					<Kicker>Four eras</Kicker>
					<h2>One code, four eras, cut by what happened</h2>
					<p className="sub">
						Nothing was reset, and nothing was deployed after d761. The eras below are cut by events in the world, not by
						code: Tallybird's failure, Halloran's first warning, and the day its loan was cleared.
					</p>
					<div className="regimes four">
						{ERAS.map((e) => (
							<div key={e.id} className={e.alert ? "rg r3" : "rg"}>
								<span className="rg-pr">
									{e.id} · {e.days}
								</span>
								<b>{e.name}</b>
								<p>{e.body}</p>
								<div className="n">{e.n}</div>
								{e.alert && <span className="badge b-bad fail">✕ {e.alert}</span>}
							</div>
						))}
					</div>
					<p className="ident">
						<code>engine.changed</code> fires four times in the window, at d515, d650, d719 and d761, the last for the
						deploy of Day 3's own report. <code>sim_meta.engine_sha</code> has read 45f7bb4 since. A month is 1,056 ticks without
						exception, so every month below is the same length of simulated time.
					</p>
				</section>

				<section id="halloran">
					<Kicker>Halloran</Kicker>
					<h2>How Halloran nearly failed, and what saved it</h2>
					<p className="sub">
						Every line below is a row in the event log, the ledger or the timesheets. Nothing outside the world touched it
						between d761 and d15,988.
					</p>
					<div className="grid2">
						<Fig title="What happened, in order">
							<ol className="tl">
								{TIMELINE.map((e) => (
									<li key={e.d} className={e.k}>
										<span className="when">{e.d}</span>
										<p>{e.t}</p>
									</li>
								))}
							</ol>
						</Fig>
						<div className="stack">
							<Fig
								title="Halloran's cash and its loan"
								legend="weekly, d7,000–d12,000"
								caption="The loan lifts cash by $62k at d7,921; the firm burns through it in 1,600 days. Interest is added to the loan in the weeks there is no cash to pay it."
							>
								<LineChart
									series={[
										{ name: "cash", color: "--hp", values: hal.cash },
										{ name: "loan owed", color: "--bad", values: hal.loan },
									]}
									xs={halDays}
									endLabels
									h={250}
									mt={40}
									yfmt={dollars}
									xfmt={dayx}
									aria="Halloran's weekly cash and loan balance, days 7,000 to 12,000"
									vlines={[halAt(7921), halAt(9552), halAt(10917)]}
									notes={[
										{ i: halAt(7921), v: hal.cash[halAt(7928)] ?? 0, text: "loan" },
										{ i: halAt(10794), v: 0, text: "$91" },
									]}
								/>
							</Fig>
							<Fig
								title="Share of worked hours that were logged"
								legend="Halloran, 6-month mean"
								caption="Only logged time is billed. The share sits near 66% for 350 months, then jumps to 88% as the departures are replaced, and stays there."
							>
								<LineChart
									series={[{ name: "logged", color: "--hp", values: after.cut(smooth(D.logged, 6)) }]}
									xs={after.xs}
									area
									yMin={0.5}
									yTicks={[0.5, 0.6, 0.7, 0.8, 0.9, 1]}
									h={230}
									yfmt={(v) => pct(v)}
									xfmt={dayx}
									aria="Share of Halloran's worked minutes that were logged, by sim-month"
									vlines={after.lines}
								/>
							</Fig>
						</div>
					</div>

					<div className="grid2 mt">
						<Fig
							title="Who logs their hours"
							legend="share logged, d511–d15,987"
							caption={
								<>
									Whether to log a day is <code>time.log</code>, asked of each person, and the person's diligence moves it.
									The three who logged least all left unpaid. The two billable hires who stayed log 74% and 95%.
								</>
							}
						>
							<BarChart
								cats={LOGGERS.map((l) => l.name)}
								values={LOGGERS.map((l) => l.share)}
								colors={LOGGERS.map((l) => (l.left ? "--bad" : "--hp"))}
								max={1}
								rowH={28}
								fmt={(v) => pct(v)}
								aria="Share of worked minutes each Halloran employee logged"
								tipf={(i) => {
									const l = LOGGERS[i];
									if (!l) return null;
									return (
										<>
											<b>{l.name}</b>
											<TipRow label="role">{l.role}</TipRow>
											<TipRow label="tenure">{l.fate}</TipRow>
											<TipRow label="logged">{pct(l.share, 1)}</TipRow>
											<TipRow label="diligence">{l.diligence.toFixed(2)}</TipRow>
											<TipRow label="unbilled">{dollars(l.unbilled)}</TipRow>
										</>
									);
								}}
							/>
						</Fig>
						<div className="stack">
							<Callout title="Diligence, not the economy.">
								Halloran's deficit was about $420 a month. Had Nadia and Owen logged 95% of their hours, as Julian and
								Emerson do, the firm would have billed about $10k a month more, which is almost exactly what its revenue
								rose by once they were replaced: $43.5k a month in E2, $53.5k in E4.
							</Callout>
							<Callout title="The loan cost more than it lent.">
								$62,215 at d7,921, at 0.25% a week. Repayment waits for twelve weeks of outgoings in the bank, so the
								firm paid interest for 3,482 days: $75,268, 121% of the principal. Maeve answered ‘borrow’ 92 more
								times; a firm that owes the bank cannot borrow again, and each answer was dropped without a trace.
							</Callout>
							<Callout title="Nobody chose the cure.">
								<code>hire.decision</code> asks whether to fill a desk, not whom; a new person's traits are drawn from
								the seed (CORE-0009). The first hire, Casey, logged 41% and left unpaid too. Halloran was rescued by
								two good draws, and its mean mood rose from 1.29 to 1.68 with them.
							</Callout>
						</div>
					</div>
				</section>

				<section id="economy">
					<Kicker>The economy</Kicker>
					<h2>Three firms, and money that stops moving</h2>
					<p className="sub">
						Cash at the end of each sim-month, summed from 5.7 million ledger entries. Dashed lines mark Tallybird's failure
						(d532), Halloran's first warning (d7,616) and its loan cleared (d11,396). Click a firm to hide it.
					</p>
					<Fig
						title="Cash by firm"
						legend={<SeriesToggle series={cashSeries} hidden={hidden} onChange={setHidden} />}
						caption="Ledgerline adds about $7.3k a month for 552 months and never spends it. Third Rail drifts from $285k to $246k. Halloran's line is the crisis: $132k down to $176 at month 350, then $1.43M. Hide Ledgerline to see it."
					>
						<LineChart
							series={cashSeries}
							xs={END}
							endLabels
							h={330}
							yfmt={money}
							xfmt={dayx}
							aria="Cash by firm at the end of each sim-month, days 28 to 15,988"
							vlines={ERA_LINES}
						/>
					</Fig>
					<div className="grid2 mt">
						<Fig
							title="Money velocity, replayed"
							legend="share of the town's cash coming in each week"
							caption="Revenue and wages flowing into the town's cash in a week, over the cash it holds. API-0004's line is 5%. It is last met in month 50: the flows are flat while Ledgerline's pile grows, so the reading sinks to 0.8%."
						>
							<LineChart
								series={[
									{ name: "velocity", color: "--mark", values: after.cut(D.velocity) },
									{ name: "detector line", color: "--dim", values: after.xs.map(() => 0.05) },
								]}
								xs={after.xs}
								endLabels
								yTicks={[0, 0.02, 0.04, 0.06, 0.08]}
								h={230}
								yfmt={(v) => pct(v, 0)}
								xfmt={dayx}
								aria="Weekly inflow to the town's cash as a share of the cash it holds, by sim-month"
								vlines={after.lines}
							/>
						</Fig>
						<Fig
							title="Halloran's revenue and spending"
							legend="per sim-month, 12-month mean"
							caption="Spending barely moves: wages are fixed and every desk is refilled. Revenue is what logged hours bill, and it steps up by $10k a month after the turnover."
						>
							<LineChart
								series={[
									{ name: "revenue", color: "--hp", values: after.cut(smooth(D.rev.halloran, 12)) },
									{ name: "spending", color: "--bad", values: after.cut(smooth(D.exp.halloran, 12)) },
								]}
								xs={after.xs}
								endLabels
								yMin={30000}
								yTicks={[30000, 40000, 50000, 60000]}
								h={230}
								yfmt={dollars}
								xfmt={dayx}
								aria="Halloran's monthly revenue and expenses, 12-month trailing mean"
								vlines={after.lines}
							/>
						</Fig>
					</div>
					<div className="grid2 mt">
						<Callout title="The cafe is fed from outside.">
							Third Rail made 2,735,038 sales worth $17.8M, a steady 4,790 a month (4,691 at the least, 4,880 at the most).
							98% were to its 100 customers, whose money comes from outside the town. Its revenue covers its costs to within
							$70 a month.
						</Callout>
						<Callout title="Households hold three weeks and spend the rest.">
							Households end every month with about $83,000, three weeks of wages, because everything above that is spent
							outside the town. They passed on $47.6M of wages and kept none of it. Tallybird's $44,489 has not moved
							since d546.
						</Callout>
					</div>
				</section>

				<section id="people">
					<Kicker>People</Kicker>
					<h2>A society in steady state</h2>
					<p className="sub">
						The 16 people who outlived Tallybird, month by month. Outside Halloran's crisis the lines are flat to within a
						few hundredths for 15,000 days.
					</p>
					<div className="grid2">
						<Fig
							title="Mean mood by firm"
							legend="agent.tick answers, 0–3"
							caption="Ledgerline sits at 1.70 and Third Rail at 1.73 throughout. Halloran falls to 1.03 at the worst of its crisis (months 340–380) and comes back at 1.68, higher than the 1.29 it held before: the new staff are cheerier people."
						>
							<LineChart
								series={[
									{ name: "Halloran", color: "--hp", values: after.cut(D.mood.halloran) },
									{ name: "Ledgerline", color: "--ll", values: after.cut(D.mood.ledgerline) },
									{ name: "Third Rail", color: "--tr", values: after.cut(D.mood.thirdrail) },
								]}
								xs={after.xs}
								endLabels
								yMin={0.8}
								yTicks={[0.8, 1.2, 1.6, 2]}
								h={240}
								yfmt={(v) => v.toFixed(1)}
								xfmt={dayx}
								aria="Mean mood by firm, by sim-month"
								vlines={after.lines}
							/>
						</Fig>
						<Fig
							title="Meetings per sim-month"
							legend="encounters, episodes, friction"
							caption="About 610 encounters and 50 multi-round episodes a month. Friction never reaches zero in any month after Tallybird (about 14 a month), but nine in ten of those events are invoice disputes."
						>
							<LineChart
								series={[
									{ name: "encounters", color: "--mark", values: after.cut(D.ev.encounter) },
									{ name: "episodes", color: "--sand", values: after.cut(D.ev.episode) },
									{ name: "friction", color: "--bad", values: after.cut(D.friction) },
								]}
								xs={after.xs}
								endLabels
								h={240}
								yfmt={(v) => fmt(v)}
								xfmt={dayx}
								aria="Encounters, episodes and friction events per sim-month"
								vlines={after.lines}
							/>
						</Fig>
					</div>
					<div className="grid2 mt">
						<Callout title="402 of 404 insolvency facts were false.">
							The shock deck seeds a rumour about every 38 days, and rumours travel like facts (MEM-0003). Ledgerline,
							the richest firm in town, was said to be failing 116 times. The two true ones were Tallybird's and Halloran's;
							Halloran's reached 17 people.
						</Callout>
						<Callout title="More promises broken than kept.">
							560 promises to pay a bill were made in conversation; 246 were kept and 314 broken. Money is 27–34% of what
							people bring up, and most (34%) in the months of Halloran's crisis.
						</Callout>
					</div>
				</section>

				<section id="model">
					<Kicker>The model</Kicker>
					<h2>Questions that have stopped being questions</h2>
					<p className="sub">
						Jev answers each typed question with a probability per option, and the answer is drawn or taken as the most
						likely. Over 6.0 million decisions, several sets returned one answer every time.
					</p>
					<div className="grid2">
						<Fig
							title="Share of each set's most common answer"
							legend="whole window"
							caption="Four sets never varied: 10,637 decisions, each a model call that could have been a constant. The honest ones sit near a coin flip: whether to log a day, defer a bill or dispute it."
						>
							<BarChart
								cats={ONE_ANSWER.map((a) => a.set)}
								values={ONE_ANSWER.map((a) => a.share)}
								colors={ONE_ANSWER.map((a) => (a.share >= 0.999 ? "--bad" : "--mark"))}
								max={1}
								rowH={26}
								fmt={(v) => pct(v, v >= 0.999 ? 0 : 1)}
								aria="Share of the most common answer in each question set"
								tipf={(i) => {
									const a = ONE_ANSWER[i];
									if (!a) return null;
									return (
										<>
											<b>{a.set}</b>
											<TipRow label="decisions">{fmt(a.n)}</TipRow>
											<TipRow label="most common">{a.top}</TipRow>
											<TipRow label="share">{pct(a.share, 1)}</TipRow>
										</>
									);
								}}
							/>
						</Fig>
						<Fig
							title="Tier 1 on dispute resolution"
							legend="agrees with Jev / escalated, by issuer"
							caption="Tier 1 (GLM 5.3 Flash, in shadow) agrees with Jev on every Ledgerline and Third Rail dispute. On Halloran's it disagrees almost every time while Halloran is short of cash, putting 0.5 on ‘discount’, and agrees again once the firm recovers."
						>
							<div className="tbl">
								<table>
									<thead>
										<tr>
											<th>months</th>
											<th className="n">Halloran cash</th>
											<th className="n">Halloran</th>
											<th className="n">Ledgerline</th>
											<th className="n">Third Rail</th>
										</tr>
									</thead>
									<tbody>
										{TIER1_DISPUTES.map((r) => (
											<tr key={r.era}>
												<td>{r.era}</td>
												<td className="n">{money(D.cash.halloran[r.m] ?? 0)}</td>
												<td className="n">
													{pct(r.hp[0] / r.hp[1])} <span className="mono">({fmt(r.hp[1])})</span>
												</td>
												<td className="n">{pct(r.ll[0] / r.ll[1])}</td>
												<td className="n">{pct(r.tr[0] / r.tr[1])}</td>
											</tr>
										))}
									</tbody>
								</table>
							</div>
						</Fig>
					</div>
					<Callout title="The second opinion draws a map of the crisis.">
						Jev stands firm on a disputed bill at any runway. The shadow model wants to give ground when the firm is short,
						so its disagreement follows Halloran's cash: it sets in around month 100, when the firm held about six weeks of
						outgoings and 4,800 sim-days before its first warning, and lifts as the loan is cleared. All 12,037 shadow
						answers in the window came from 103 calls; the rest were cached. On{" "}
						<code>founder.review</code>, tier 1 agrees with Jev only 140 times in 900.
					</Callout>
				</section>

				<section id="run">
					<Kicker>The run</Kicker>
					<h2>The model meets fewer new situations every month</h2>
					<p className="sub">
						A call is new when its exact bytes have never been sent; otherwise the cache answers (DECIDE-0004). New calls
						are placed in the sim-month that was running when they were made.
					</p>
					<div className="grid2">
						<Fig
							title="New model calls per sim-month"
							legend="log scale, 6-month mean"
							caption="About 2,400 a month in E1, 196 just after Tallybird, 50 by month 150 and 22 in E4. Agent ticks have all but stopped being new; what novelty is left is conversation. Halloran's crisis raised it from 31 a month to 47."
						>
							<LineChart
								series={[
									{ name: "agent.tick", color: "--mark", values: novelty.tick },
									{ name: "episode.round", color: "--sand", values: novelty.round },
									{ name: "the rest", color: "--dim", values: novelty.other },
								]}
								xs={END}
								endLabels
								yTicks={[0, 1, 2, 3, 4]}
								h={250}
								yfmt={(v, tip) => (tip ? `≈${pow10(v)} a month` : pow10(v))}
								xfmt={dayx}
								aria="New model calls per sim-month on a log scale, by kind"
								vlines={ERA_LINES}
							/>
						</Fig>
						<Fig
							title="Cache hit rate"
							legend="Jev decisions, 6-month mean"
							caption="Share of Jev's decisions answered by a call made earlier. 88.8% in E1, 98.9% in E2, 99.4% through the crisis and 99.7% in E4."
						>
							<LineChart
								series={[{ name: "hit rate", color: "--mark", values: smooth(D.hit, 6) }]}
								xs={END}
								area
								yMin={0.8}
								yTicks={[0.8, 0.85, 0.9, 0.95, 1]}
								h={250}
								yfmt={(v) => pct(v, 1)}
								xfmt={dayx}
								aria="Cache hit rate by sim-month"
								vlines={ERA_LINES}
							/>
						</Fig>
					</div>
					<Fig title="Decisions, calls and cost by era" className="mt">
						<div className="tbl">
							<table>
								<thead>
									<tr>
										<th>era</th>
										<th className="n">sim-days</th>
										<th className="n">wall days</th>
										<th className="n">decisions</th>
										<th className="n">gated</th>
										<th className="n">new calls</th>
										<th className="n">cost</th>
										<th className="n">per sim-year</th>
										<th className="n">cache hit</th>
									</tr>
								</thead>
								<tbody>
									{ERA_COST.map((r) => (
										<tr key={r.e}>
											<td>{r.e}</td>
											<td className="n">{fmt(r.days)}</td>
											<td className="n">{r.wall.toFixed(1)}</td>
											<td className="n">{fmt(r.dec)}</td>
											<td className="n">{pct(r.gated)}</td>
											<td className="n">{fmt(r.calls)}</td>
											<td className="n">${r.usd.toFixed(2)}</td>
											<td className="n">${((r.usd / r.days) * 365).toFixed(3)}</td>
											<td className="n">{pct(r.hit, 1)}</td>
										</tr>
									))}
								</tbody>
							</table>
						</div>
					</Fig>
					<div className="grid2 mt">
						<Fig
							title="Wall hours per sim-month"
							caption="A sim-month takes a median of 2.28 wall hours early on and 2.37 at the end. Seven months took 22–40 hours. Those stops account for about 10 of the 66 wall days, and nothing in the database says why."
						>
							<LineChart
								series={[{ name: "wall hours", color: "--sand", values: D.wall_h }]}
								xs={END}
								h={230}
								yfmt={(v) => `${Math.round(v)}h`}
								xfmt={dayx}
								aria="Wall-clock hours each sim-month took"
								vlines={ERA_LINES}
							/>
						</Fig>
						<div className="stack">
							<Callout title="Two-thirds of the database is one count.">
								Before tier 1 may ask a second opinion, <code>room()</code> counts yesterday's decisions. There is no
								index on <code>decisions.sim_time</code>, so each call reads all 5.76 million rows: a 21.6 s median, 1,116
								times in a week, 66.6% of database time. At about 15 calls a sim-month it adds some 5 minutes to each, which is
								the whole of the 4% by which a month has slowed. It is the shape LLM-0010 removed from the spend ledger, and
								it grows by 10,500 rows a month.
							</Callout>
							<Callout title="The public report has stopped answering.">
								<code>GET /report</code> gave no answer within 300 s three times, once after this report's reads had
								stopped; <code>GET /economics</code> once. Day 3 measured /report at 19–40 s. Since then the decisions it
								folds have grown elevenfold and the ledger entries twentyfold.
							</Callout>
						</div>
					</div>
				</section>

				<section id="novelty">
					<Kicker>What is new here</Kicker>
					<h2>Four claims, each with its evidence and its limit</h2>
					<p className="sub">
						Claimed against the project's own survey of prior art (<code>docs/research/01</code>). That is one search, not
						proof.
					</p>
					<div className="claims">
						<div className="claim">
							<h3>A typed-decision society runs for decades of sim-time for under three dollars</h3>
							<p>
								15,988 sim-days, 16 to 24 working people and 400 counterparties, 6.0M decisions: $2.89 in model calls,
								and a cent a sim-year once the cache is warm.
							</p>
							<p className="caveat">
								The price is the cache. A world that stops producing new situations stops costing money, and also stops
								telling the model anything new.
							</p>
						</div>
						<div className="claim">
							<h3>A macro crisis and recovery, 7,000 days after the last deploy</h3>
							<p>
								Halloran's slide, loan, missed paydays, turnover and recovery came from typed micro-decisions
								(<code>time.log</code>, <code>leave.consider</code>, <code>hire.decision</code>) and the rules that
								settle money. No code changed between d761 and d15,988.
							</p>
							<p className="caveat">
								One firm, one seed, one trajectory. The link to diligence rests on seven people.
							</p>
						</div>
						<div className="claim">
							<h3>Novelty decays without stopping</h3>
							<p>
								New calls per month fell by two orders of magnitude, from 2,390 to 22, and are still falling. A crisis
								raises them for as long as it lasts.
							</p>
							<p className="caveat">
								Measured under fixed wording and one model build. Rewording a set restarts its curve (Day 3 saw this at
								d511).
							</p>
						</div>
						<div className="claim">
							<h3>A second model's disagreement marks where the world is under strain</h3>
							<p>
								Tier 1 agrees with Jev on disputes everywhere except Halloran's, and only while Halloran was short of
								cash, for 300 months.
							</p>
							<p className="caveat">Shadow only, 103 distinct calls, and one question set.</p>
						</div>
					</div>
				</section>

				<section id="defects">
					<Kicker>Defects</Kicker>
					<h2>Found in the data, traced to the code</h2>
					<p className="sub">New since Day 3 unless it says otherwise. Each shows up in production rows or measurements.</p>
					<Defects items={DEFECTS} />
				</section>

				<section id="next">
					<Kicker>Recommendations</Kicker>
					<h2>What to change next, in order</h2>
					<p className="sub">Ordered by what each costs the running world and the research question.</p>
					<ol className="recs">
						<li>
							<b>Count tier 1's allowance from a running total.</b>
							<span>
								Keep decisions per sim-day as a row the tick updates, or index <code>decisions(sim_time)</code>, and add
								the query to <code>test_query_plans.py</code>. Do the same for <code>cash_of</code>: a balance per
								account, moved by every posting, as LLM-0010 did for spend.
							</span>
						</li>
						<li>
							<b>Make /report and /economics incremental.</b>
							<span>They no longer answer at all. Fold from running totals, or snapshot once per sim-day.</span>
						</li>
						<li>
							<b>Give profit somewhere to go.</b>
							<span>
								Owner draws, investment or competition, so Ledgerline's $4.3M and Halloran's new $1.4M return to
								households and the cafe, and money velocity measures something other than a growing pile.
							</span>
						</li>
						<li>
							<b>Make the loan a bridge.</b>
							<span>
								Repay on a schedule, or from eight weeks of cash, and take ‘borrow’ off the menu while a loan is
								outstanding, or record the refusal.
							</span>
						</li>
						<li>
							<b>Bring back a software vendor.</b>
							<span>Day 3's first recommendation. The outage, ticket and churn loops have been absent for 15,455 days.</span>
						</li>
						<li>
							<b>Retire the questions that have one answer.</b>
							<span>
								<code>dispute.resolution</code>, <code>supplier.order</code> and <code>cover.shift</code> either get
								inputs that matter or become rules. Tier 1 already shows what one of those inputs is: the firm's runway.
							</span>
						</li>
						<li>
							<b>Treat novelty as a health signal.</b>
							<span>
								New calls per month is the cheapest measure of whether the world is still producing situations. Put it on
								/report next to the eight detectors.
							</span>
						</li>
						<li>
							<b>Keep a status history.</b>
							<span>One row per status change in sim_meta's place, so a 40-hour stop has a reason.</span>
						</li>
					</ol>

					<Kicker className="spaced">Threats to validity</Kicker>
					<ul className="method">
						<li>
							One world and one seed, with no control arm. Halloran's recovery is a single trajectory; its link to
							diligence comes from seven people's timesheets, not a designed comparison.
						</li>
						<li>
							E1 ran under four versions of the code (Day 1 and Day 3 cover it). Everything from d761 ran under one.
						</li>
						<li>
							New calls are placed in sim-months by their wall-clock creation time, using the latest call each month's
							decisions used as its end. A month lasts about 2.3 wall hours; the placement can be off by a fraction of
							one.
						</li>
						<li>
							Cost by era is new calls times each kind's mean cost per call; the total ($2.89) is the sum of recorded
							call costs.
						</li>
						<li>
							Money velocity is replayed from revenue and wage flows by month, not from the detector's own query, which no
							longer finishes.
						</li>
						<li>
							The town replay's rates come from <code>agent.tick</code> answers in the last 13 sim-months, which
							over-weight lunch (Day 3 used movement intervals; that query is too large to run against production now).
						</li>
					</ul>

					<Kicker className="spaced">Method</Kicker>
					<ul className="method">
						<li>
							Production Postgres was read through PlanetScale's ephemeral <code>pg_read_all_data</code> role between
							07:01 and 07:45 UTC on 27 November 2026; nothing was written. Query time comes from PlanetScale's insights
							for the seven days before, and CPU from its branch metrics.
						</li>
						<li>
							The window is <code>tick_seq &lt; 602,977</code>: sim-days 0–15,987, the last complete 28-day sim-month
							inside the first 16,000 days. The daemon ticks exactly 1,056 times a month, so months were cut by tick.
						</li>
						<li>
							Decisions were read in 25 id ranges of 250,000; events by kind through <code>events_kind_tick</code>;
							ledger flows by month from the first entry of each month's first transaction. About 90 queries ran one at
							a time, each inside the role's 45-second statement timeout. Nine that failed (two timeouts, seven with an
							error in the SQL) were rewritten and run again.
						</li>
						<li>
							<code>GET /report</code>, <code>GET /economics</code> and <code>GET /state</code> were timed from a cloud
							session between 07:11 and 07:30 UTC.
						</li>
						<li>Semantics and line references are from the source at commit 45f7bb4, the one production runs.</li>
					</ul>
					<SiteFooter>
						<span>jeve · run golden-20260920 · root seed 20260920</span>
						<span>report generated 2026-11-27</span>
					</SiteFooter>
				</section>
			</div>
		</TipProvider>
	);
}
