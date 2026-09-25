"use client";

/**
 * "Day 3 in Prod": the second field report, as published on 2026-09-25.
 *
 * Frozen on purpose, like Day 1. It reads only what happened after Day 1's
 * snapshot (seq 82,494, sim day 232) and treats the three deploys since as
 * interventions on one running world. Its numbers are the production database
 * read between 03:09 and 03:40 UTC that night through a read-only role, plus
 * the public GET /report at 03:19 (`data.json` holds the series; the smaller
 * tables are constants below, each with the query it came from in the PR).
 */
import { BarChart, ColChart, LineChart, type Series } from "@/components/report/charts";
import { dayfmt, dollars, fmt, pad2 } from "@/components/report/format";
import {
	type AnswerRow,
	AnswerTables,
	Callout,
	type Defect,
	Defects,
	Effects,
	Fig,
	Kicker,
	ReportBar,
	Say,
	SeriesToggle,
	Vital,
	WhoLegend,
} from "@/components/report/parts";
import { TipProvider, TipRow } from "@/components/report/tip";
import { TownReplay } from "@/components/report/TownReplay";
import type { TownData } from "@/components/report/town";
import { SiteFooter } from "@/components/SiteFooter";
import { useMemo, useState } from "react";
import raw from "./data.json";

type Staff = { id: string; org: string; role: string; name: string; seat: [number, number]; spot?: [number, number]; path: [number, number][] };
type Data = {
	lunch: { hours: number[]; R1: number[]; R3b: number[] };
	cash: { first_day: number; households: number[] } & Record<"tallybird.cash" | "halloran.cash" | "ledgerline.cash" | "thirdrail.cash", number[]>;
	cache: { d: number; n: number; new: number }[];
	weekly: { wk: number; friction: number; enc: number; eps: number; inc: number; warn: number }[];
	town: {
		kinds: Record<string, string>;
		tiles: string[];
		queue: [number, number][];
		staff: Staff[];
		people: Record<string, { cafe: number; talk: number; mood: number }>;
		cafeShare: Record<string, number>;
		arrivals: Record<string, number>;
	};
	lookup: Record<string, AnswerRow[]>;
};
const D = raw as unknown as Data;
const FIRST = D.cash.first_day;
/** A sim-day as an index into the daily series. */
const at = (day: number) => day - FIRST;

const NAV: [string, string][] = [
	["summary", "summary"],
	["experiment", "the experiment"],
	["scorecard", "scorecard"],
	["collapse", "the collapse"],
	["economy", "economy"],
	["people", "people"],
	["model", "the model"],
	["run", "the run"],
	["novelty", "what's new"],
	["defects", "defects"],
	["next", "next"],
];

// -- the scorecard: Day 1's eight recommendations, as shipped and as measured ---

type Verdict = "works" | "partly" | "mixed" | "watch" | "triggered" | "clear" | "too few";
const VERDICT: Record<Verdict, string> = {
	works: "b-good",
	clear: "b-good",
	partly: "b-warn",
	mixed: "b-warn",
	watch: "b-mark",
	"too few": "b-mark",
	triggered: "b-bad",
};

const RECS: { id: string; ask: string; shipped: string; measured: string; v: Verdict }[] = [
	{ id: "1", ask: "Make insolvency matter, then recalibrate Tallybird", shipped: "WORLD-0010: staff decide whether to leave, the head reviews, four missed paydays is failure; seats priced per seat", measured: "Tallybird failed on d533, 22 sim-days after the deploy. Its first repriced bill ($43,081) went out the day before", v: "mixed" },
	{ id: "2", ask: "Close the household loop", shipped: "WORLD-0010: a purse per employer, weekly spending, rent, supplier stock, quarterly tax", measured: "Third Rail's cash is flat (−1.5% over 231 days; it had risen $152k in the 286 before). One artefact: 93.5% of $1.63M in savings was spent in a single tick at the upgrade", v: "works" },
	{ id: "3", ask: "Put the economy into perception", shipped: "WORLD-0009: nine things can be on someone's mind, money first", measured: "Mood is 0.07 when wages are unpaid and 2.12 on payday, against 1.63 on an ordinary day. 34% of ticks now carry something on the mind (5.7% before)", v: "works" },
	{ id: "4", ask: "Canonicalise the roster", shipped: "WORLD-0009: a room is at most three firms, described by count", measured: "Cache hit 89.6% → 92.2%; new model calls per open day 94 → 23", v: "works" },
	{ id: "5", ask: "Ask agent.tick only when something changed", shipped: "WORLD-0009: decision points instead of every quarter hour", measured: "Asks per staff member per open day 31 → 10.7 (−65%). The lunch peak held (22.7% → 23.6% of office staff at the cafe at 13:30); encounters per staff-day halved", v: "works" },
	{ id: "6", ask: "Fix the defects", shipped: "#26 phase 0: autopay gate, payment provenance, round counts, notices, engine SHA", measured: "317 standing-instruction payments by rule, 0.00–0.07 days late; payments now say who decided (317 rules, 109 Jev); outcome.rounds is a number", v: "works" },
	{ id: "7", ask: "Give “how likely” questions a situation that matters", shipped: "The new question sets are written with concrete situations; the old ones were reworded", measured: "New sets follow the situation (vendor.trust: history 0.23 against temperament 0.14). Old ones still follow temperament (file.ticket: 0.33 against 0.01)", v: "partly" },
	{ id: "8", ask: "Stamp the engine SHA", shipped: "sim_meta.engine_sha, and an engine.changed event per deploy", measured: "54d76f4 is stamped; three later deploys are events at d514.6, d649.6 and d718.7", v: "works" },
];

const REVERSALS: { id: string; cond: string; measured: string; v: Verdict }[] = [
	{ id: "WORLD-0008", cond: "Depth two stays a sliver after a live week, or the daily ceiling binds on most days", measured: "Depth two: 12 of 189 episodes in R2, 1 of 242 in R3. Ceiling of 12: never reached (10 at most)", v: "watch" },
	{ id: "WORLD-0009", cond: "The lunch curve or the encounter rate collapses against golden-20260920, or mood still ignores the situation", measured: "Lunch peak 22.7% → 23.6%. Encounters per staff-day 3.2 → 1.6. Mood 0.07–2.12 by what is on the mind", v: "watch" },
	{ id: "WORLD-0010", cond: "Firms fail in most seeded runs on rules, or never come near the edge under Jev", measured: "One failure, of a firm 355 days unpaid when the rule arrived; the other three never went below $116k", v: "clear" },
	{ id: "WORLD-0011", cond: "A loop's decision shows no persona or situation dependence under Jev", measured: "dispute.resolution: 103 of 103 stand firm; no input moves it more than 0.09", v: "triggered" },
	{ id: "WORLD-0012", cond: "Handoffs are relayed almost always under Jev", measured: "One handoff in 231 sim-days, relayed", v: "too few" },
	{ id: "MEM-0003", cond: "Trust never moves under Jev except where the rules twin would have moved it", measured: "77 revisions; trust follows outage history (0.23) and whether a report was answered (0.10)", v: "clear" },
	{ id: "DECIDE-0005", cond: "Agreement inside the bands exceeds 95% for every set", measured: "92.7% overall (204 of 220); founder.review 1 of 14", v: "clear" },
	{ id: "API-0004", cond: "A detector fires on healthy runs so often that people stop reading", measured: "Friction fires in the weeks between monthly dispute batches; money velocity sits at 0.047 against a 0.05 line", v: "watch" },
];

// -- the collapse ---------------------------------------------------------------

const TIMELINE: { d: string; t: string; k?: "bad" | "mark" }[] = [
	{ d: "d511.6", k: "mark", t: "#26 deploys into the running world. Tallybird has $11,450 and has not met a payroll since day 156. The new failure rule starts counting missed paydays from zero." },
	{ d: "d512.4", t: "Payday missed (1 of 4). Rent is paid: $4,000." },
	{ d: "d515.4", t: "Dana, the founder, reviews: cut costs (0.76) over borrowing (0.22). Cutting costs sets a frugal flag. Wages, the actual problem, are untouched." },
	{ d: "d519.4", t: "Missed (2). Sara, an engineer (P(leave) 0.45), and Petra, the engineering lead (0.58), quit." },
	{ d: "d520.4", t: "The payroll held since day 156 is finally released: $10,500, 460 sim-days late. The next is held. Ingrid, account manager (0.53), and Kwame, support (0.50), quit. An insolvency warning fires inside the review cooldown, so Dana is not asked again." },
	{ d: "d526.4", t: "Missed (3). Ruth, the support lead (0.38), quits." },
	{ d: "d532.4", t: "Renewal round: 51 customers asked, 26 cancel, Halloran's two seats among them. 23 get a 25% retention offer. The first per-seat bill goes out: 79 invoices, $43,081, due d546." },
	{ d: "d533.4", k: "bad", t: "Missed (4). Tallybird fails with $1,408. Dana, Mikel and Tomas leave by rule, all 79 subscriptions end, and outages stop reaching anyone." },
	{ d: "d546–560", t: "All 79 invoices are paid, to a firm that no longer exists. Tallybird's cash climbs to $44,489." },
];

/** leave.consider: the highest P(leave) each person was given, and what happened. */
const LEAVE = [
	["Petra · eng lead", 0.58, "quit d519"],
	["Ingrid · account mgr", 0.53, "stayed d519, quit d520"],
	["Kwame · support", 0.5, "stayed d519, quit d520"],
	["Sara · engineer", 0.45, "quit d519"],
	["Tomas · sre", 0.43, "stayed three times; left at failure"],
	["Ruth · support lead", 0.38, "stayed twice, quit d526"],
	["Mikel · engineer", 0.18, "stayed three times; left at failure"],
] as const;

// -- people -------------------------------------------------------------------

const MOOD = [
	["It is payday", 2.12, 5917],
	["Nothing unusual", 1.63, 23622],
	["A colleague has just quit", 1.0, 6],
	["Timetrack down", 0.57, 21],
	["A rough week", 0.47, 4059],
	["Invoicing down", 0.44, 52],
	["A promise to pay was broken", 0.38, 502],
	["POS down", 0.25, 4],
	["Wages not paid", 0.07, 1580],
] as const;

const TOPICS = [
	["Day 1", 3.2, 61.7, 24.2],
	["R1", 2.7, 63.4, 25.0],
	["R2", 2.9, 63.1, 25.1],
	["R3 · collapse", 58.3, 31.3, 9.4],
	["R3 · after", 30.5, 39.2, 29.5],
] as const;

// -- the model ----------------------------------------------------------------

/** Main-effect ranges over R3's cached calls (one row per distinct request). */
const EFFECTS: Record<string, Record<string, number>> = {
	"vendor.trust": { history: 0.233, before: 0.167, temperament: 0.14, handled: 0.103, outage: 0.089 },
	"subscription.renew": { trust: 0.21, reliance: 0.067, temperament: 0.063 },
	"invoice.dispute": { size: 0.363, temperament: 0.224, bill: 0.198 },
	"time.log": { work_habit: 0.532, backlog: 0.377 },
	"leave.consider": { temperament: 0.275, attitude_to_risk: 0.227, wages: 0.089 },
	"dispute.resolution": { client: 0.087, bill: 0.048 },
	"chase.invoice": { temperament: 0.558, cash: 0.453, invoice: 0.219, size: 0.056 },
	"ticket.confirm": { temperament: 0.505, ticket: 0.11 },
	"file.ticket": { temperament: 0.333, what_it_stops: 0.014 },
};
const EFFECT_ORDER = Object.keys(EFFECTS);

/** Tier 1 in shadow: GLM 5.3 Flash re-asked when Jev was unsure. Rows that agreed. */
const TIER1 = [
	["dispute.resolution", 98, 98],
	["invoice.dispute", 60, 60],
	["retention.offer", 23, 23],
	["ticket.triage", 10, 10],
	["leave.consider", 9, 10],
	["subscription.renew", 2, 2],
	["credit.decision", 0, 2],
	["founder.review", 1, 14],
] as const;

// -- the run ------------------------------------------------------------------

const PER_DAY = [
	["Day 1", 1015, "--dim"],
	["R1", 1032, "--dim"],
	["R2", 1021, "--dim"],
	["collapse", 545, "--mark"],
	["after", 415, "--mark"],
] as const;

const REGIME_COST = [
	{ r: "R1 · Day-1 code + episodes", days: 148, calls: 13932, usd: 0.589, hit: 0.896 },
	{ r: "R2 · #21", days: 93, calls: 8933, usd: 0.378, hit: 0.893 },
	{ r: "R3 · #26 + #28", days: 199, calls: 4498, usd: 0.159, hit: 0.922 },
];

/** Settled spend per six wall hours, UTC (spend_entries). */
const SPEND6 = [
	["23 06", 0.157],
	["23 12", 0.238],
	["23 18", 0.273],
	["24 00", 0.227],
	["24 06", 0.199],
	["24 12", 0.035],
	["24 18", 0.026],
	["25 00", 0.013],
] as const;

const DETECTORS: { l: string; v: string; line: string; fires: boolean }[] = [
	{ l: "Friction per week", v: "0", line: "fires at 0", fires: true },
	{ l: "Share of the town's cash that changes hands in a week", v: "0.047", line: "fires below 0.05", fires: true },
	{ l: "Model answers that reached for ‘other’", v: "7.1% (132 of 1,852)", line: "fires above 5%", fires: true },
	{ l: "Acts that always come out the same", v: "none of 5 collapsed", line: "fires at any", fires: false },
	{ l: "What a person's job says about where they go", v: "0.66 of the entropy", line: "fires below 0.05", fires: false },
	{ l: "How differently the two ends of a trait act", v: "z 6.1 and 7.4", line: "fires if no z ≥ 2", fires: false },
	{ l: "Second opinions that only ever agree", v: "2 in band this week", line: "needs 200 rows", fires: false },
	{ l: "Support away from the desk with a backlog", v: "no backlog", line: "fires above 30%", fires: false },
];

const DEFECTS: Defect[] = [
	{ s: "critical", t: "A failed firm keeps collecting its receivables", b: "Failure is absorbing: the firm bills nobody and employs nobody. But the 79 invoices Tallybird issued the day before it failed were all paid to it afterwards, $43,081 into the account of a firm that no longer exists. Had the rule looked at receivables, it would have seen nearly a month of wages in flight.", loc: "py/src/jeve/world/economy.py:827 fail() · invoices from tallybird issued d532.4, paid d546–560" },
	{ s: "high", t: "Missing a payroll makes the month look profitable", b: "The founder's review compares money in with money out over the month. Wages that were never paid are not money out, so in the same prompt that says wages could not be paid, Dana read “More money has come in this month than has gone out.”", loc: "py/src/jeve/decide/questions.py trend_words · economy.py _trend" },
	{ s: "high", t: "‘Other’ is silently recorded as holding course", b: "At the two professional firms, Jev's most likely answer to the monthly review was ‘other’ (0.52–0.76) in 17 of 18 reviews. The interpreter rewrites ‘other’ to hold_course, so the log shows 27 healthy reviews that all chose to carry on. The menu has no way to grow, invest or hire.", loc: "questions.py _interpret_review · founder.review distributions d515–d739" },
	{ s: "high", t: "Dispute resolution is a rule wearing a question", b: "All 103 disputes were resolved ‘stand firm’, from six distinct calls; no input moves the answer more than 0.09. That is the condition WORLD-0011 names for reversal.", loc: "dispute.resolution · 103 decisions, 6 calls" },
	{ s: "high", t: "Production's budget counts spend that isn't production's", b: "The ceiling is enforced against max(local, OpenRouter meter − baseline). The meter rose $2.37 between 07:48 and 11:49 UTC on 24 Sep while the daemon settled $0.11. Effective spend is $6.65 against a $16 halt, of which about $4.5 was spent elsewhere on the same key.", loc: "py/src/jeve/llm/ledger.py:63 effective_usd · spend_entries kind=remote" },
	{ s: "note", t: "The new loops do not cite their causes", b: "subscription.cancelled (26), time.lost (89) and close.rework (7) carry empty causes, and firm.failed cites only a rules payroll.held. The cascade happened, but the log cannot walk it back to the leave decisions or the outages that drove churn.", loc: "events.causes · recursive walk from firm.failed seq 190924" },
	{ s: "note", t: "The upgrade spent 93.5% of household savings in one tick", b: "Splitting the single household account into purses per employer ran the weekly spending rule against 500 sim-days of savings: $1,526,168 of $1,632,368 left in one transaction at d511.65. Every households-spending ratio that spans the upgrade includes it.", loc: "ledger_txns 89921–89925" },
	{ s: "note", t: "The live report no longer fits inside a tick", b: "GET /report took 39.9 s and then 19.3 s. At speed 120 a tick passes in about 7.5 wall seconds, so the per-tick memo (API-0003) never hits and every visitor pays for a full recompute.", loc: "py/src/jeve/api/report.py · measured 03:19–03:21 UTC" },
	{ s: "note", t: "One warning in 22 days of collapse reached the founder", b: "A review is requested on every warning but not within a week of the last. Tallybird's only warning in R3 came five days after its review, and the monthly one was due after the failure.", loc: "economy.py request_review REVIEW_COOLDOWN" },
];

// -- the scale calculator -----------------------------------------------------

/** Measured in R3: new model calls per staff member per open day, and mean cost per call. */
const R3_CALLS_PER_STAFF_DAY = 1.36;
const R3_USD_PER_CALL = 0.0000353;
/** docs/research/01-prior-art-mapping.md: Smallville, one saved 3-agent sim-day. */
const SMALLVILLE_CALLS_PER_AGENT_DAY = 1257;

function ScaleCalc() {
	const [staff, setStaff] = useState(225);
	const [rate, setRate] = useState(R3_CALLS_PER_STAFF_DAY);
	const calls = staff * rate;
	const usd = calls * R3_USD_PER_CALL;
	return (
		<div className="calc">
			<div>
				<label htmlFor="calc-staff">
					<span>
						staff in the world: <b>{fmt(staff)}</b>
					</span>
					<input id="calc-staff" type="range" min={16} max={2000} step={1} value={staff} onChange={(e) => setStaff(+e.target.value)} />
				</label>
				<label htmlFor="calc-rate">
					<span>
						new model calls per staff member per open day: <b>{rate.toFixed(2)}</b>
					</span>
					<input id="calc-rate" type="range" min={0.5} max={6} step={0.01} value={rate} onChange={(e) => setRate(+e.target.value)} />
				</label>
				<p className="cap">
					Starts at the measured R3 rate (1.36) and PR #15's district (225 staff). Raise the rate for a colder
					cache: more firms mean more distinct situations, and the rules census already shows the hit rate
					falling as question sets are added. Cost per call is R3's mean, ${R3_USD_PER_CALL.toFixed(7)}.
				</p>
			</div>
			<div className="vitals">
				<Vital n={fmt(calls)}>new model calls per open day</Vital>
				<Vital n={`$${usd < 0.1 ? usd.toFixed(3) : usd.toFixed(2)}`}>per open sim-day</Vital>
				<Vital n={`$${(usd * 300).toFixed(2)}`}>per sim-year of about 300 open days</Vital>
				<Vital n={`${fmt(SMALLVILLE_CALLS_PER_AGENT_DAY * staff)}`}>calls a day at Smallville's measured rate</Vital>
			</div>
		</div>
	);
}

function Verdicts({ v }: { v: Verdict }) {
	return <span className={`badge ${VERDICT[v]}`}>{v}</span>;
}

function townData(): TownData {
	const T = D.town;
	const num = (r: Record<string, number>) => Object.fromEntries(Object.entries(r).map(([k, v]) => [+k, v]));
	return {
		tiles: T.tiles.map((row) => [...row].map((c) => T.kinds[c] ?? "grass")),
		cast: T.staff.map((s) => ({ ...s, org_id: s.org })),
		queue: T.queue,
		people: T.people,
		cafeShare: num(T.cafeShare),
		arrivals: num(T.arrivals),
		// Encounter topics after the failure (d533–d742).
		topics: [
			["small talk", 0.392],
			["money", 0.305],
			["work", 0.295],
			["other", 0.007],
		],
		buildings: [
			{ org_id: "tallybird", zone: "software_office", name: "Tallybird Software", x0: 2, y0: 2, x1: 15, y1: 10, cash: 44489, flag: "failed d533", note: "failed d533 · 4 paydays missed" },
			{ org_id: "halloran", zone: "law_office", name: "Halloran & Pike LLP", x0: 24, y0: 2, x1: 37, y1: 10, cash: 134603 },
			{ org_id: "ledgerline", zone: "accounting_office", name: "Ledgerline Accounting", x0: 2, y0: 17, x1: 15, y1: 25, cash: 370644 },
			{ org_id: "thirdrail", zone: "cafe", name: "Third Rail Cafe", x0: 24, y0: 17, x1: 37, y1: 25, cash: 282152 },
		],
		outage: null,
		day: "d742 replay",
		cashLabel: "cash at d742",
	};
}

const FIRMS: [keyof Data["cash"], string, string][] = [
	["tallybird.cash", "Tallybird", "--tb"],
	["halloran.cash", "Halloran & Pike", "--hp"],
	["ledgerline.cash", "Ledgerline", "--ll"],
	["thirdrail.cash", "Third Rail", "--tr"],
];

export function Day3InProd() {
	const town = useMemo(townData, []);
	const [hidden, setHidden] = useState<Set<string>>(new Set());

	const days = D.cash["tallybird.cash"].map((_, i) => FIRST + i);
	const cashSeries: Series[] = FIRMS.map(([k, name, color]) => ({
		name,
		color,
		values: D.cash[k] as number[],
		hidden: hidden.has(name),
	}));

	// Tallybird's last weeks, d500–d565.
	const tbFrom = 500;
	const tbTo = 565;
	const tb = D.cash["tallybird.cash"].slice(at(tbFrom), at(tbTo) + 1);
	const tbDays = tb.map((_, i) => tbFrom + i);

	const cache = useMemo(() => {
		const raw = D.cache.map((x) => 1 - x.new / Math.max(1, x.n));
		const sm = raw.map((_, i) => {
			const w = raw.slice(Math.max(0, i - 6), i + 1);
			return w.reduce((a, b) => a + b, 0) / w.length;
		});
		const xs = D.cache.map((x) => x.d);
		const idx = (d: number) => Math.max(0, xs.findIndex((x) => x >= d));
		return { xs, sm, r2: idx(403), r3: idx(512) };
	}, []);

	const wk = D.weekly;
	const wkDays = wk.map((w) => w.wk * 7);
	const wkIdx = (d: number) => Math.max(0, wkDays.findIndex((x) => x >= d));

	return (
		<TipProvider>
			<ReportBar sub="field report · day 3 · golden-20260920" links={NAV} />
			<div className="page">
				<TownReplay data={town} clock="d742 replay" booksId="economy">
					The same street at d742, with the 16 people still working on it. Tallybird's office is empty: its eight staff
					left between d519 and d533, five by their own decision. The replay is rebuilt from measured rates after the
					failure: where each person spends their ticks, cafe arrivals by hour, and what people talk about, which is now
					money nearly a third of the time. Hover anyone, or click a building for its books.
				</TownReplay>

				<header id="summary" className="summary">
					<Kicker>Field report · day 3 · production run golden-20260920</Kicker>
					<h1>Consequences arrived. Tallybird lasted 22 days.</h1>
					<p className="lede">
						Day 1 found a world where nothing had consequences. Three deploys later, it has them. This report reads only
						what happened after Day 1's snapshot: sim days 232 to 742, 42 wall hours, 332,395 typed decisions. It treats
						each deploy as an experiment on a society that never stopped running.
					</p>
					<div className="status">
						<span>
							<b>d232 → d742</b>
						</span>
						<span>tick 28,000</span>
						<span>seq 82,494 → 246,179</span>
						<span className="badge b-good">● running · lag 0 s · no error</span>
						<span className="badge b-mark">jev-1.13-20260917</span>
						<span>engine 54d76f4</span>
						<span>snapshot 2026-09-25 03:09 UTC · read-only</span>
					</div>

					<div className="vitals">
						<Vital n="510" unit="sim-days">
							in 42 wall hours, under three versions of the code
						</Vital>
						<Vital n="332k">typed decisions; 27,361 new model calls</Vital>
						<Vital n="5×">
							cheaper per open day after #26: $0.0008 against $0.0040, with the cache hit rate up to 92%
						</Vital>
						<Vital n="22" unit="days" alert>
							from the first consequence to Tallybird's failure
						</Vital>
						<Vital n="0.07">mean mood when wages are unpaid; on Day 1 unpaid staff averaged 1.47</Vital>
						<Vital n="3 / 8" alert>
							degeneracy detectors firing: no friction this week, slow money, answers reaching for ‘other’
						</Vital>
					</div>

					<Say by="the short version">
						All eight changes Day 1 asked for shipped, and each shows up in production. Unpaid people are miserable, off-lunch trips to the cafe halved, and the model bill fell fivefold. But the consequences landed on a firm that
						had been insolvent for 355 sim-days. <em>Tallybird failed on its fourth missed payday</em>, one day after
						sending $43k of repriced invoices that would have covered nearly a month of wages. When it went, it took the town's
						main causal loop with it: outages, tickets, escalations and churn.
					</Say>
				</header>

				<section id="experiment">
					<Kicker>The experiment</Kicker>
					<h2>Three deploys into a running world</h2>
					<p className="sub">
						Nothing was reset. Each deploy migrated the live database, and the daemon picked up the new code on its next
						tick, so the window is one world under three regimes. Each regime is cut at its migration's timestamp and
						confirmed by behaviour only the new code can produce.
					</p>
					<div className="regimes">
						<div className="rg">
							<span className="rg-pr">R1 · baseline</span>
							<b>Day-1 code, plus episodes (#14)</b>
							<p>What Day 1 described, with multi-round conversations switched on at its snapshot.</p>
							<div className="n">d232 → d403 · 171 sim-days · 14.4 h · 152,718 decisions</div>
						</div>
						<div className="rg">
							<span className="rg-pr">R2 · #21</span>
							<b>Rounds remember, recursion two deep</b>
							<p>Conversations see their last round and nest two levels; hearsay and promises reach decisions.</p>
							<div className="n">d403 → d511 · 108 sim-days · 9.3 h · 94,954 decisions</div>
						</div>
						<div className="rg r3">
							<span className="rg-pr">R3 · #26 (+ #28)</span>
							<b>Consequences, perception, decision points, the scenario's loops</b>
							<p>
								Built from Day 1's recommendations: 16 new question sets, 46 new kinds of event, tier 1 in shadow, a
								ledger that reads one row.
							</p>
							<div className="n">d511 → d742 · 231 sim-days · 18.7 h · 84,996 decisions</div>
							<span className="badge b-bad fail">✕ Tallybird fails at d533</span>
						</div>
					</div>
					<p className="ident">
						R1 → R2: migration 0010 at 23:09:11 UTC; the last <code>settled</code> answer key is at sim 34,855,200 and the
						first <code>done</code> and <code>stalled</code> at 34,866,900. R2 → R3: migrations 0011–0013 at 08:24:59 UTC;
						fifteen question sets that never existed first appear at sim 44,206,200. R3 is split at the failure (R3 ·
						collapse, d511–d533; R3 · after, d533–d742), because the world after it has one firm fewer.
					</p>

					<Kicker className="spaced">How a decision is made</Kicker>
					<ol className="pipe">
						<li>
							<b>A situation arises</b>
							<span>A payday is missed, a bill falls due, someone walks into the cafe. Code decides when to ask.</span>
						</li>
						<li>
							<b>A gate, if the answer is forced</b>
							<span>Rules settle it for free: no cash, no queue, a standing instruction. 33% of decisions after the failure.</span>
						</li>
						<li>
							<b>A typed question</b>
							<span>The situation in plain words and a fixed set of options; Jev returns a probability for each one.</span>
						</li>
						<li>
							<b>A draw, or the most likely</b>
							<span>Propensities are sampled, judgements take the argmax, each seeded by what the draw is about.</span>
						</li>
						<li>
							<b>An event, and the books</b>
							<span>The choice becomes an event with causes, money moves double-entry, and nothing reads generated text.</span>
						</li>
					</ol>
				</section>

				<section id="scorecard">
					<Kicker>Scorecard</Kicker>
					<h2>Day 1 asked for eight changes. All eight shipped.</h2>
					<p className="sub">
						Each of Day 1's recommendations, what PR #26 built for it, and what production did next. Measured on R3 against
						R1 unless the row says otherwise.
					</p>
					<Fig>
						<div className="tbl">
							<table className="score">
								<thead>
									<tr>
										<th>#</th>
										<th>Day 1 asked</th>
										<th>shipped as</th>
										<th>measured in production</th>
										<th>verdict</th>
									</tr>
								</thead>
								<tbody>
									{RECS.map((r) => (
										<tr key={r.id}>
											<td className="id">{r.id}</td>
											<td className="what">{r.ask}</td>
											<td>{r.shipped}</td>
											<td className="m">{r.measured}</td>
											<td className="v">
												<Verdicts v={r.v} />
											</td>
										</tr>
									))}
								</tbody>
							</table>
						</div>
					</Fig>

					<Kicker className="spaced">Pre-registered reversal conditions</Kicker>
					<p className="sub">
						Every decision record behind these deploys says in advance what would make it wrong. Here is each condition
						against the data.
					</p>
					<Fig>
						<div className="tbl">
							<table className="score">
								<thead>
									<tr>
										<th>record</th>
										<th>reverse it if</th>
										<th>measured</th>
										<th>status</th>
									</tr>
								</thead>
								<tbody>
									{REVERSALS.map((r) => (
										<tr key={r.id}>
											<td className="id">{r.id}</td>
											<td>{r.cond}</td>
											<td className="m">{r.measured}</td>
											<td className="v">
												<Verdicts v={r.v} />
											</td>
										</tr>
									))}
								</tbody>
							</table>
						</div>
					</Fig>
				</section>

				<section id="collapse">
					<Kicker>The collapse</Kicker>
					<h2>Tallybird's last 22 days</h2>
					<p className="sub">
						Day 1 ended with Tallybird 11 weeks unpaid and nothing happening. By the time #26 arrived it was 50 weeks.
						WORLD-0010 gave it four paydays to recover in. Every line below is a row in the event log.
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
								title="Tallybird's cash"
								legend="d500–d565"
								caption="Rent and one backlog payroll take it under $1,500. It fails at $1,408. Two weeks later its customers pay the repriced bill, into an account nobody draws on."
							>
								<LineChart
									series={[{ name: "Tallybird", color: "--tb", values: tb }]}
									xs={tbDays}
									area
									h={230}
									mt={40}
									yfmt={dollars}
									xfmt={dayfmt}
									aria="Tallybird's cash, days 500 to 565"
									vlines={[at(511) - at(tbFrom), at(533) - at(tbFrom)]}
									notes={[
										{ i: at(533) - at(tbFrom), v: tb[at(533) - at(tbFrom)] ?? 0, text: "fails · d533" },
										{ i: at(546) - at(tbFrom), v: tb[at(546) - at(tbFrom)] ?? 0, text: "$43k arrives" },
									]}
								/>
							</Fig>
							<Fig
								title="Who left, and how sure Jev was"
								legend="highest P(leave) asked"
								caption={
									<>
										<code>leave.consider</code> is sampled, not argmax: Ingrid stayed at 0.53 and left the next day at the same
										0.53. Temperament moves P(leave) by 0.28 and appetite for risk by 0.23; another week unpaid moves it by
										0.01–0.07.
									</>
								}
							>
								<BarChart
									cats={LEAVE.map((l) => l[0])}
									values={LEAVE.map((l) => l[1])}
									colors={LEAVE.map((l) => (l[2].includes("quit") ? "--bad" : "--tb"))}
									max={1}
									rowH={26}
									fmt={(v) => v.toFixed(2)}
									aria="Highest probability of leaving given to each Tallybird employee"
									tipf={(i) => (
										<>
											<b>{LEAVE[i]?.[0]}</b>
											<TipRow label="P(leave)">{LEAVE[i]?.[1].toFixed(2)}</TipRow>
											<div className="m">{LEAVE[i]?.[2]}</div>
										</>
									)}
								/>
							</Fig>
						</div>
					</div>
					<Callout title="Liquidity, not solvency.">
						At the new per-seat prices Tallybird bills about $43k a month against $45.5k of wages ($10.5k a week), close to
						viable. It failed the day after its first repriced bill went out, with that bill two weeks from due. The failure
						rule counts missed paydays and sees no receivables. Borrowing was on the menu at 0.22, and Dana was asked once.
					</Callout>
				</section>

				<section id="economy">
					<Kicker>The economy</Kicker>
					<h2>Three firms settle; the street gets quieter</h2>
					<p className="sub">
						Cash at the end of each sim-day from 270,957 ledger entries that still sum to exactly zero. Dashed lines mark
						#21 (d403), #26 (d511) and the failure (d533). Click a firm to hide it.
					</p>
					<Fig
						title="Cash by firm"
						legend={<SeriesToggle series={cashSeries} hidden={hidden} onChange={setHidden} />}
						caption="Third Rail rose in a straight line until #26 because its customers were paid for from outside. Since #26 it pays rent, stock and tax, and its cash is flat: $284,774 at d511, $280,496 at d742. Ledgerline keeps growing (+$91k) and paid $8,506 in tax. Halloran saws between $117k and $163k."
					>
						<LineChart
							series={cashSeries}
							xs={days}
							endLabels
							h={330}
							yfmt={dollars}
							xfmt={dayfmt}
							aria="Cash by firm, days 225 to 744"
							vlines={[at(403), at(511), at(533)]}
							notes={[{ i: at(533), v: D.cash["tallybird.cash"][at(533)] ?? 0, text: "Tallybird fails" }]}
						/>
					</Fig>
					<div className="grid2 mt">
						<Fig
							title="Friction per sim-week"
							legend="payroll, leavers, disputes, churn…"
							caption="The twelve kinds of event API-0004 counts as friction. Before #26 there were about 0.5 a week. After it, 4.8, near the rules forecast of 4.2, but two-thirds are the monthly batch of disputes. Between the batches most weeks have zero to two (11 of the 29 weeks after the failure have none), and a week with none trips the detector."
						>
							<LineChart
								series={[{ name: "friction", color: "--bad", values: wk.map((w) => w.friction) }]}
								xs={wkDays}
								h={230}
								yfmt={(v) => String(Math.round(v))}
								xfmt={dayfmt}
								aria="Friction events per sim-week"
								vlines={[wkIdx(403), wkIdx(511)]}
								notes={[{ i: wkIdx(532), v: 41, text: "collapse week · 41" }]}
							/>
						</Fig>
						<Fig
							title="Encounters and outages per sim-week"
							caption="Decision points ask less often, so people meet less: about 465 encounters a week before, about 157 after the failure. The last outage began on d527; once Tallybird failed, its software had no customers left for an outage to reach."
						>
							<LineChart
								series={[
									{ name: "encounters", color: "--mark", values: wk.map((w) => w.enc) },
									{ name: "outages × 50", color: "--tb", values: wk.map((w) => w.inc * 50) },
								]}
								xs={wkDays}
								endLabels
								h={230}
								yfmt={(v) => String(Math.round(v))}
								xfmt={dayfmt}
								aria="Encounters and outages per sim-week"
								vlines={[wkIdx(403), wkIdx(511)]}
							/>
						</Fig>
					</div>
					<div className="grid2 mt">
						<Callout title="Halloran loses a quarter of its billable value.">
							The law firm now bills logged hours, and whether to log is a decision (<code>time.log</code>, logged 44% of
							the time). Of 177,356 minutes worked, 111,719 were logged; 57,181 minutes, $121,918 at its rates, were never
							billed.
						</Callout>
						<Callout title="Every dispute ends the same way.">
							Clients disputed 100 of 235 bills they were asked about, driven mostly by bill size (0.36). All 103 disputes
							were resolved ‘stand firm’: $378k contested and not a dollar conceded. Money moves at 4.7% of the town's
							cash a week.
						</Callout>
					</div>
				</section>

				<section id="people">
					<Kicker>The people</Kicker>
					<h2>What's on their mind now reaches their mood, and their talk</h2>
					<p className="sub">
						On Day 1, mood had one lever (an outage) and unpaid Tallybird staff were happier than paid lawyers. #26 gave
						the prompt nine things someone can have on their mind.
					</p>
					<div className="grid2">
						<Fig
							title="Mood by what's on their mind"
							legend="R3, mean on a 0–3 scale"
							caption="Unpaid wages take mood to 0.07; payday lifts it to 2.12. 34% of agent.tick answers in R3 carry something on the mind, against 5.7% in R1, when it could only be an outage."
						>
							<BarChart
								cats={MOOD.map((m) => m[0])}
								values={MOOD.map((m) => m[1])}
								max={3}
								color="--mark"
								fmt={(v) => `${v.toFixed(2)} / 3`}
								aria="Mean mood by what is on their mind"
								tipf={(i) => (
									<>
										<b>{MOOD[i]?.[0]}</b>
										<TipRow label="mean mood">{MOOD[i]?.[1]}</TipRow>
										<TipRow label="decisions">{fmt(MOOD[i]?.[2] ?? 0)}</TipRow>
									</>
								)}
							/>
						</Fig>
						<Fig
							title="Office staff at the cafe"
							legend="at half past each hour"
							caption="Rebuilt from where each person actually was, not from what they were asked. The lunch peak survived decision points (22.7% → 23.6% at 13:30); outside lunch, time at the cafe roughly halved, and by two-thirds mid-morning."
						>
							<LineChart
								series={[
									{ name: "R1", color: "--dim", values: D.lunch.R1 },
									{ name: "R3 · after", color: "--tr", values: D.lunch.R3b },
								]}
								xs={D.lunch.hours}
								endLabels
								h={250}
								yTicks={[0, 0.1, 0.2, 0.3]}
								yfmt={(v) => `${Math.round(v * 100)}%`}
								xfmt={(h, tip) => (tip ? `${pad2(h)}:30` : `${h}h`)}
								aria="Share of office staff at the cafe by hour, R1 against R3"
							/>
						</Fig>
					</div>
					<Fig
						title="What they talk about"
						legend="share of encounters, %"
						className="mt"
						caption="During the 22 days of Tallybird's collapse, more than half of all conversations were about money; afterwards, nearly a third. Before #26 money was 3%. Second-hand knowledge rose from 8% of what people learned in R1 to 21% in R3, and a fact travelled four hops for the first time. Three rumours were false: all said Halloran was in trouble, and Halloran never was."
					>
						<div className="tbl">
							<table>
								<thead>
									<tr>
										<th>regime</th>
										<th className="n">money</th>
										<th className="n">small talk</th>
										<th className="n">work</th>
									</tr>
								</thead>
								<tbody>
									{TOPICS.map((t) => (
										<tr key={t[0]}>
											<td>{t[0]}</td>
											<td className="n">{t[1].toFixed(1)}</td>
											<td className="n">{t[2].toFixed(1)}</td>
											<td className="n">{t[3].toFixed(1)}</td>
										</tr>
									))}
								</tbody>
							</table>
						</div>
					</Fig>
					<Callout title="Conversations still circle rather than end.">
						Of 242 episodes in R3, 68% stalled (everyone repeated their last act, mostly small talk), 28% ran out of
						rounds, and none settled. Depth two occurred once. The same pattern held in R2, where 2 of 189 settled: argmax on ‘done’, asked of everyone at once, almost never comes out yes for all of them.
					</Callout>
				</section>

				<section id="model">
					<Kicker>What moves the model</Kicker>
					<h2>Where the question names the situation, Jev follows it</h2>
					<p className="sub">
						The widest swing in Jev's probability as one input changes, averaged over the rest, across R3's cached calls
						(main-effect range, 0–1). The first six sets are new in #26; the last three were asked on Day 1 too.
					</p>
					<Fig
						caption="Trust follows outage history and whether a report was answered; renewal follows trust; disputes follow the bill's size. The old “how likely” questions still answer to temperament: how much an outage stops someone's work moves filing a ticket by 0.014. Dispute resolution follows nothing."
					>
						<WhoLegend />
						<Effects effects={EFFECTS} order={EFFECT_ORDER} />
					</Fig>
					<AnswerTables tables={D.lookup} initial="founder.review" storageKey="jeve-lt3" />
					<div className="grid2 mt">
						<Fig
							title="Tier 1 in shadow"
							legend="GLM 5.3 Flash agreeing with Jev"
							caption="When Jev is unsure, a flash model is asked the same typed question and nothing is applied. 204 of 220 agreed, for $0.004. The one set where it disagreed is the one where Jev's own answer is mostly ‘other’."
						>
							<BarChart
								cats={TIER1.map((t) => t[0])}
								values={TIER1.map((t) => t[1] / t[2])}
								colors={TIER1.map((t) => (t[1] / t[2] < 0.5 ? "--bad" : "--good"))}
								max={1}
								rowH={24}
								fmt={(v) => `${Math.round(v * 100)}%`}
								aria="Share of tier-1 answers agreeing with Jev, by question set"
								tipf={(i) => (
									<>
										<b>{TIER1[i]?.[0]}</b>
										<TipRow label="agreed">
											{TIER1[i]?.[1]} of {TIER1[i]?.[2]}
										</TipRow>
									</>
								)}
							/>
						</Fig>
						<Callout title="The menu is missing an option.">
							Pick <code>founder.review</code> in the table above and read its last column. At Halloran and Ledgerline Jev puts 0.52–0.76 on
							‘other’, most months, because a firm with plenty of cash has nothing on the list to do but carry on. The
							interpreter records ‘other’ as holding course, so the log shows 27 healthy reviews in a row. In the last seven sim-days, 7.1% of modelled choices put 0.35 or more on ‘other’, and the ontology-gap detector fires.
						</Callout>
					</div>
				</section>

				<section id="run">
					<Kicker>The run</Kicker>
					<h2>Fivefold cheaper per day, on a budget shared with others</h2>
					<p className="sub">
						The daemon shows no error at the snapshot, applied three deploys in place, and kept the ledger balanced to the cent.
					</p>
					<div className="grid2">
						<Fig
							title="Decisions per open sim-day"
							caption="Decision points halved the decisions a day before Tallybird failed; losing eight of 24 staff took another quarter. The mix changed too: a third are now settled by a gate, free."
						>
							<ColChart
								cats={PER_DAY.map((p) => p[0])}
								values={PER_DAY.map((p) => p[1])}
								colors={PER_DAY.map((p) => p[2])}
								h={240}
								yfmt={(v) => fmt(v)}
								valLabels={PER_DAY.map((p) => fmt(p[1]))}
								aria="Decisions per open sim-day by regime"
								tipf={(i) => (
									<>
										<b>{PER_DAY[i]?.[0]}</b>
										<TipRow label="decisions a day">{fmt(PER_DAY[i]?.[1] ?? 0)}</TipRow>
									</>
								)}
							/>
						</Fig>
						<Fig
							title="Cache hit rate by sim-day"
							legend="7-day mean"
							caption="Share of Jev decisions answered by an existing call. #26 reworded almost every question, so the cache restarted cold at d511 (70–75%) and climbs back as the new wording fills in. Over all of R3, 92.2% of Jev decisions reused a call."
						>
							<LineChart
								series={[{ name: "hit rate", color: "--mark", values: cache.sm }]}
								xs={cache.xs}
								area
								yMin={0.5}
								yTicks={[0.5, 0.6, 0.7, 0.8, 0.9, 1]}
								h={240}
								yfmt={(v) => `${Math.round(v * 100)}%`}
								xfmt={dayfmt}
								aria="Cache hit rate by sim-day"
								vlines={[cache.r2, cache.r3]}
							/>
						</Fig>
					</div>
					<Fig title="Model calls and cost by regime" className="mt">
						<div className="tbl">
							<table>
								<thead>
									<tr>
										<th>regime</th>
										<th className="n">open days</th>
										<th className="n">new calls</th>
										<th className="n">calls / day</th>
										<th className="n">cost</th>
										<th className="n">cost / day</th>
										<th className="n">cache hit</th>
									</tr>
								</thead>
								<tbody>
									{REGIME_COST.map((r) => (
										<tr key={r.r}>
											<td>{r.r}</td>
											<td className="n">{r.days}</td>
											<td className="n">{fmt(r.calls)}</td>
											<td className="n">{(r.calls / r.days).toFixed(1)}</td>
											<td className="n">${r.usd.toFixed(3)}</td>
											<td className="n">${(r.usd / r.days).toFixed(4)}</td>
											<td className="n">{(r.hit * 100).toFixed(1)}%</td>
										</tr>
									))}
								</tbody>
							</table>
						</div>
					</Fig>
					<div className="grid2 mt">
						<Fig
							title="Spend per six wall hours"
							legend="settled, UTC"
							caption="From about $0.24 per six hours before #26 to about $0.03 after. The window cost $1.13 in model calls."
						>
							<ColChart
								cats={SPEND6.map((s) => s[0])}
								values={SPEND6.map((s) => s[1])}
								colors={SPEND6.map((_, i) => (i >= 5 ? "--mark" : "--dim"))}
								h={220}
								yfmt={(v) => `$${v.toFixed(2)}`}
								aria="Settled model spend per six wall hours"
								tipf={(i) => (
									<>
										<b>Sep {SPEND6[i]?.[0]}:00 UTC</b>
										<TipRow label="settled">${SPEND6[i]?.[1].toFixed(3)}</TipRow>
									</>
								)}
							/>
						</Fig>
						<Callout title="Most of production's budget was not spent by production.">
							The governor enforces the larger of the local ledger and OpenRouter's meter for the key. The meter rose $2.37
							in the four hours after 07:48 UTC on 24 Sep, while the daemon settled $0.11. Production reads
							$6.65 against its $16 halt, of which about $4.5 was spent elsewhere on the same key. The $12 line closes tier
							1 first.
						</Callout>
					</div>
					<Fig title="Degeneracy detectors, live" legend="GET /report at 03:19 UTC, last seven sim-days" className="mt">
						<div className="tbl">
							<table>
								<thead>
									<tr>
										<th>detector</th>
										<th>reading</th>
										<th>line</th>
										<th>state</th>
									</tr>
								</thead>
								<tbody>
									{DETECTORS.map((d) => (
										<tr key={d.l}>
											<td>{d.l}</td>
											<td>{d.v}</td>
											<td>{d.line}</td>
											<td>
												<span className={`badge ${d.fires ? "b-bad" : "b-good"}`}>{d.fires ? "fires" : "quiet"}</span>
											</td>
										</tr>
									))}
								</tbody>
							</table>
						</div>
					</Fig>
				</section>

				<section id="novelty">
					<Kicker>What is new here</Kicker>
					<h2>Four claims, each with its evidence and its limit</h2>
					<p className="sub">
						Novelty is claimed against the project's own survey of prior art (<code>docs/research/01</code>), which found
						no system that replaces a Smallville-style loop with typed questions. That is one search, not proof.
					</p>
					<div className="claims">
						<article className="claim">
							<h3>A society run on typed decisions, at about one billed call per person-day</h3>
							<p>
								After #26: 4,498 new model calls over 199 open days, about 1.4 per staff member per day, and $0.0008 a day
								for the whole town. The survey measured roughly 1,257 language-model calls per agent-day for Smallville.
								Every model decision is stored with its full distribution, every gated one with its rule, and all of it replays for free.
							</p>
							<div className="caveat">
								Not like for like: Smallville's agents also write prose, and this cache is 500 sim-days warm. Counting all
								416 people who act, it is 0.05 calls per agent-day.
							</div>
						</article>
						<article className="claim">
							<h3>Deploys as interventions on one continuous world</h3>
							<p>
								Three versions of the code ran in a single world without a reset. Each is identified by its migration and
								by behaviour only it can produce, and each decision record's reversal condition was checked against
								production. Nothing had to be seeded twice.
							</p>
							<div className="caveat">
								No parallel control arm: regimes are adjacent stretches of sim time, so drift (Tallybird's cash, a warming
								cache) sits inside every before-and-after difference.
							</div>
						</article>
						<article className="claim">
							<h3>Macro cascades out of typed micro-choices</h3>
							<p>
								Five sampled decisions to leave, then a fourth missed payday, a firm failure, 79 subscriptions ending and
								the outage loop gone. Outages moved trust 77 times, and the renewal round that followed lost 26 customers. Crisis talk rose from 3% of
								conversations to 58%. The survey's main risk for typed agents was “no novelty”: closed menus that cannot
								produce a cascade.
							</p>
							<div className="caveat">
								The log records the cascade but cannot walk all of it: firm.failed cites one rules-decided payroll.held, and
								cancellations cite nothing.
							</div>
						</article>
						<article className="claim">
							<h3>A second model's disagreement points at holes in the question</h3>
							<p>
								Tier 1 agreed with Jev on 204 of 220 uncertain answers. It disagreed where Jev itself put 0.52–0.76 on
								‘other’: the founder's review, whose menu has no option a healthy firm would take. Agreement measures
								redundancy; disagreement locates an ontology gap.
							</p>
							<div className="caveat">14 rows on the one set, and shadow only: nothing was applied.</div>
						</article>
					</div>

					<Kicker className="spaced">What is viable, and what is not yet</Kicker>
					<div className="grid2">
						<Callout title="Viable now.">
							Typed judgement questions that name the situation (trust, renewal, disputes). Cache economics that improve
							with time. Decision points that keep the day's shape at a third of the asks. Perception wired to the books.
							In-place upgrades: three deploys, no errors, the ledger at zero. Detectors that notice when the world goes
							quiet.
						</Callout>
						<Callout title="Not yet.">
							Failure is absorbing and has no successor, so one bankruptcy deleted the scenario's central loop. Menus lack
							options (‘other’ becomes hold course). One loop is a rule in disguise. New events don't cite their causes.
							The budget is shared with other work, and the live report has outgrown a tick.
						</Callout>
					</div>

					<Kicker className="spaced">What it would cost to scale</Kicker>
					<Fig caption="A projection, not a measurement: it holds R3's cost per call fixed and asks what the call rate does. The measured rate includes conversation rounds (1,095 of R3's 4,498 calls), whose share grows with how often people have something at stake, not with head count.">
						<ScaleCalc />
					</Fig>
				</section>

				<section id="defects">
					<Kicker>Defects</Kicker>
					<h2>Found in the data, traced to the code</h2>
					<p className="sub">
						New since Day 1. Each shows up in production rows and traces to a line of source or a measurement.
					</p>
					<Defects items={DEFECTS} />
				</section>

				<section id="next">
					<Kicker>Recommendations</Kicker>
					<h2>What to change next, in order</h2>
					<p className="sub">Ordered by how much each one distorts the research question.</p>
					<ol className="recs">
						<li>
							<b>Give the town a software vendor again.</b>
							<span>
								Let a failed vendor be replaced, or restarted by its founder with what it is owed, so outages, tickets,
								escalation, trust and churn can happen at all. Collect a failed firm's receivables for its creditors and
								staff instead of into its own account.
							</span>
						</li>
						<li>
							<b>Let the failure rule see money in flight.</b>
							<span>
								Count receivables due within a payday, or offer a loan against them, before calling four missed paydays a
								failure. Ask the head again whenever a payroll is missed, cooldown or not.
							</span>
						</li>
						<li>
							<b>Fix the founder's review.</b>
							<span>
								Count unpaid wages as money out, and add the options a healthy firm wants (invest, hire, expand). Stop
								writing ‘other’ as hold course: record it, and let the ontology-gap detector see it.
							</span>
						</li>
						<li>
							<b>Make dispute resolution a rule, or give it something to weigh.</b>
							<span>
								WORLD-0011's reversal condition is met. Either settle it in code or put the client's history and the
								dispute's grounds into the question.
							</span>
						</li>
						<li>
							<b>Give production its own model key.</b>
							<span>
								OPS-0004 already gave agents their own; evals and re-recording should not spend production's $16.
							</span>
						</li>
						<li>
							<b>Cite causes in the new loops</b>
							<span>
								so churn walks back to the outages and trust revisions behind it, and failure to the leave decisions.
							</span>
						</li>
						<li>
							<b>Make /report incremental.</b>
							<span>It now takes 19–40 s, longer than a tick at speed 120.</span>
						</li>
						<li>
							<b>Reword the old “how likely” questions like the new ones.</b>
							<span>Trust and renewal show that concrete situations move Jev; filing a ticket still doesn't.</span>
						</li>
					</ol>

					<Kicker className="spaced">Threats to validity</Kicker>
					<ul className="method">
						<li>
							No control arm in production. Regimes are adjacent stretches of one world, so anything that drifts with sim
							time sits inside every regime difference. The comparisons made within one regime (mood by mind, main
							effects, P(leave), tier-1 agreement) avoid this.
						</li>
						<li>
							R3 changed many things at once. Decision points, perception, the economy and the loops all arrived in one
							deploy; their separate effects cannot be told apart here. PR #26's own rules comparison
							(<code>ops/field-report-v2.md</code>) is the place for that.
						</li>
						<li>
							The failure changed the population: 16 staff after d533 against 24 before. Rates are per person or per
							open day where that matters.
						</li>
						<li>
							Main-effect ranges are spreads over the contexts actually sampled (5–43 distinct calls per set), not a
							controlled design; read them as a ranking.
						</li>
						<li>Small counts: 15 leave decisions, 14 disagreeing tier-1 rows, 5 incidents in R3, 1 handoff.</li>
					</ul>

					<Kicker className="spaced">Method</Kicker>
					<ul className="method">
						<li>
							Production Postgres was read through PlanetScale's ephemeral <code>pg_read_all_data</code> role between
							03:09 and 03:40 UTC on 25 September; nothing was written. The live <code>GET /report</code> was read at 03:19
							and the Fly logs at 03:21.
						</li>
						<li>
							Only rows after Day 1's snapshot count: events after seq 82,494, decisions and knowledge after sim 20,077,200,
							model calls created after 08:48 UTC on 23 September.
						</li>
						<li>
							Office staff at the cafe is rebuilt from <code>agent.moved</code> intervals sampled at half past each hour.
							Day 1 used the share of <code>agent.tick</code> answers, which decision points bias toward whoever is at
							lunch.
						</li>
						<li>
							One analysis query from this investigation (a correlated subquery over <code>model_calls</code>, run the
							previous afternoon) timed out in the client but ran 3.9 h on the primary, 97% of database time over the
							following twelve hours. It read only; later queries were kept to single grouped scans.
						</li>
						<li>Semantics and line references are from the source at commit 54d76f4.</li>
					</ul>
					<SiteFooter>
						<span>jeve · run golden-20260920 · root seed 20260920</span>
						<span>report generated 2026-09-25</span>
					</SiteFooter>
				</section>
			</div>
		</TipProvider>
	);
}
