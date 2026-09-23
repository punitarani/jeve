"use client";

/**
 * "Day 1 in Prod": the first field report, as published on 2026-09-23.
 *
 * Frozen on purpose. Its numbers are the production database at 08:48 UTC
 * that morning (`data.json`, extracted from the published artifact unchanged)
 * and its prose was written against them, so nothing here reads the API. The
 * live report at /reports is the same set of views over data that keeps
 * moving; this is the record of what they showed the first time.
 */
import { BarChart, ColChart, Dumbbell, LineChart, type Series } from "@/components/report/charts";
import {
	AnswerTables,
	type AnswerRow,
	Callout,
	CallsTable,
	type Defect,
	Defects,
	Effects,
	EscLegend,
	Fig,
	type Finding,
	Findings,
	Kicker,
	PeopleTable,
	ReportBar,
	Say,
	SeriesToggle,
	Vital,
	WhoLegend,
} from "@/components/report/parts";
import { dayfmt, dollars, fmt, pad2 } from "@/components/report/format";
import { TipProvider, TipRow } from "@/components/report/tip";
import { TownReplay } from "@/components/report/TownReplay";
import type { TownData } from "@/components/report/town";
import { SiteFooter } from "@/components/SiteFooter";
import { useMemo, useState } from "react";
import raw from "./data.json";

type Data = {
	cash: Record<string, number[]>;
	zones: { hr: number; software_office: number; law_office: number; accounting_office: number; cafe: number; plaza: number }[];
	cafe: { hr: number; sale: number; walk: number }[];
	cache: { d: number; n: number; new: number }[];
	people: Record<"person_id" | "role" | "mood" | "cafe_pct" | "talk_pct" | "raised" | "soc" | "dil", string>[];
	effects: Record<string, Record<string, number>>;
	lookup: Record<string, AnswerRow[]>;
	town: {
		kinds: Record<string, string>;
		tiles: string[];
		staff: { id: string; org: string; role: string; name: string; seat: [number, number]; spot?: [number, number]; path: [number, number][] }[];
		queue: [number, number][];
	};
};
const D = raw as unknown as Data;

const NAV: [string, string][] = [
	["summary", "summary"],
	["findings", "findings"],
	["run", "the run"],
	["economy", "economy"],
	["people", "people"],
	["model", "the model"],
	["outages", "outages"],
	["defects", "defects"],
	["next", "next"],
];

const FINDINGS: Finding[] = [
	{ c: "economy", s: "critical", t: "Tallybird is structurally insolvent, and nothing happens", b: "Weekly wages of $14,600 against ~$5.7k a month of revenue. Payroll ran 5 times in 33 weeks, the last on day 156, averaging 34 days late. Staff keep working, lunching and ordering catering.", e: "payroll.paid tallybird n=5; payroll.held rules×3 + 147 daily retries; min cash $619 @ d157" },
	{ c: "economy", s: "critical", t: "Households are a sink, not a sector", b: "$759k of wages went into household accounts and $10.6k came back out as spending. The circular flow does not close, so demand comes from outside the model.", e: "ledger households.income −759,400 · households.spending 10,587" },
	{ c: "economy", s: "high", t: "An insolvent founder orders large catering", b: 'Tallybird ordered $420 catering four times, twice after payroll stopped. The prompt said funds were "comfortably enough", because the gate only checks cash ≥ order.', e: "catering.ordered tallybird d106, d113, d218, d232; state.funds constant in all 5 calls" },
	{ c: "economy", s: "good", t: "The books balance and bills get paid", b: "85,232 ledger entries sum to exactly zero. 1,059 payments averaged 2.06 days late; nothing is overdue at the snapshot and nothing was written off.", e: "SUM(ledger_entries.amount_cents) = 0; all open invoices pre-due" },
	{ c: "economy", s: "note", t: "Warnings without consequences", b: "151 insolvency warnings, often the same payload day after day. Nothing in the world reads them.", e: "insolvency.warning: 96 thin_reserves + 55 spending_exceeds_income; 70 distinct payloads of 96" },
	{ c: "behaviour", s: "critical", t: "Agents cannot perceive money", b: "on_their_mind has four values: an ordinary day or one of three outages. Unpaid Tallybird staff average mood 1.47, higher than fully paid Halloran staff at 1.35.", e: "SELECT DISTINCT state.on_their_mind FROM model_calls → 4 values" },
	{ c: "behaviour", s: "high", t: "Temperament outweighs situation", b: "In \"how likely\" questions the temperament word moves Jev’s probability by 0.38–0.56; the situation (outage length, ticket age, invoice size) by 0.01–0.09.", e: "main-effect ranges over 149 cached non-tick calls" },
	{ c: "behaviour", s: "good", t: "Judgement questions are sensible", b: "Credit scales with outage severity and business impact, month-end close flips on overdue bills, payroll release follows timesheets. Jev is good at institutional judgement.", e: "credit.decision: 0.84 on outage length, 0.57 on effect on customer" },
	{ c: "behaviour", s: "good", t: "A lunch rhythm nobody wrote", b: "Office staff go from 3% at the cafe at 09:00 to 31% at 13:00, and walkouts peak at 28% in the noon rush. The daily shape emerges from typed choices.", e: "agent.tick next_zone by hour, office staff; walkouts ÷ arrivals by hour" },
	{ c: "behaviour", s: "high", t: "Mood is a personality constant", b: "Mood is argmax (J mode), so 18 of 24 staff have a standard deviation of 0.4 or less. It tracks diligence (r = 0.62) and only drops during outages (1.63 → ~0.5).", e: "stddev((chosen->>mood)::int) by person" },
	{ c: "behaviour", s: "high", t: "Escalation is social, not procedural", b: "134 of 155 incidents were escalated in person, 113 of them in the cafe, onto whoever from Tallybird was there. Sociability, not role, decides who fixes things.", e: "ticket.escalated raised_with: support.6 37, engineer.3 32, eng_lead.1 1" },
	{ c: "behaviour", s: "high", t: "Talk moves nothing", b: "15,988 encounters and 1,773 outage conversations, but 3,370 of 3,371 knowledge rows are first-hand. Episodes (live since 08:17 UTC) produced the first relayed fact.", e: "knowledge.hops: 0 → 3,370 · 1 → 1" },
	{ c: "behaviour", s: "note", t: "Two of four client bases barely exist", b: "Law and accounting clients made 2.4 decisions each in 232 days, and 35% never acted at all. Cafe customers made 443 each.", e: "decisions per counterparty, by firm" },
	{ c: "architecture", s: "good", t: "232 sim-days for $0.93", b: "OpenRouter metered $0.927 since baseline; the local ledger settled $0.970 (5% conservative). About $0.004 per sim-day, $0.000005 per decision.", e: "spend_entries remote 1.2330 − baseline 0.3064; Σ settle 0.9702" },
	{ c: "architecture", s: "high", t: "The roster is the whole bill", b: "agent.tick is 99.3% of calls. Without who_is_here it has 615 distinct states; with the roster, 20,826. The cache is still minting ~100 contexts a day after day 200.", e: "COUNT(DISTINCT state − who_is_here) = 615" },
	{ c: "architecture", s: "high", t: "Everyone is asked every tick", b: "Each office worker answered agent.tick 5,331 times, and each cafe worker 8,783 times. 89% of those answers end in no encounter: the model is asked to re-confirm a quiet desk.", e: "decisions per person: 5,331 office / 8,783 cafe; interact=false 131,855 of 148,200" },
	{ c: "architecture", s: "note", t: "Gates are free and do real work", b: "24,358 decisions (12%) were settled by a gate without a model call, mostly cafe arrivals with nobody queueing.", e: "decisions.source = rules: cafe.purchase 24,084" },
	{ c: "architecture", s: "note", t: "Worst-case reservations run 11× high", b: "Reserves totalled $10.56 against $0.97 settled. Harmless at this spend, but a ceiling tuned in reserved dollars will refuse work early.", e: "Σ reserve 10.5635 vs Σ settle 0.9702" },
	{ c: "defect", s: "critical", t: '"Standing instruction" payers are asked daily', b: "The autopay fact is set but no gate reads it. The top four promptness quintiles, meant to pay on the day by rule, still go to Jev and pay 0.5–2.2 days late.", e: "engine.py:1281 sets facts.autopay; gates.py:48 never reads it" },
	{ c: "defect", s: "high", t: "Payment provenance is wrong in the table", b: "Every payments row says decided_by = rules while every payment.made event says jev. The INSERT omits the column.", e: "engine.py:1378" },
	{ c: "defect", s: "note", t: "Prompt wording mislabels roles", b: 'The model reads "a weekend at the cafe", "a engineer" and "a sre". Wording is part of the cache key, so fixing it means re-recording.', e: "model_calls.wire state.person / who_is_here" },
];
const CATS: [string, string, string][] = [
	["all", "all", "all"],
	["economy", "economy", "economy"],
	["behaviour", "agent behaviour", "agent behaviour"],
	["architecture", "architecture", "architecture"],
	["defect", "defects", "defect"],
];

const DEFECTS: Defect[] = [
	{ s: "critical", t: "Autopay is not a gate", b: 'WORLD-0005 says clients in the top four promptness quintiles pay by standing instruction on the due date. The engine skips their bills before that date, but from then on asks Jev daily like everyone else. These "autopay" clients pay 0.54–2.16 days late, and every payment is labelled jev.', loc: "py/src/jeve/world/engine.py:1264–1281 · py/src/jeve/decide/gates.py:48" },
	{ s: "high", t: "payments.decided_by is always the default", b: "The INSERT lists invoice_id, paid_sim, amount_cents, txn_id and days_late only, so all 1,059 rows carry the column default rules, while the matching payment.made events say jev.", loc: "py/src/jeve/world/engine.py:1378" },
	{ s: "high", t: "Episode outcome stores the exit reason as its round count", b: 'outcome.rounds holds the string "rounds" rather than a number, and will hold "settled" or "emptied" on other exits. The episodes.rounds column is correct (3).', loc: "py/src/jeve/world/episodes.py:869" },
	{ s: "note", t: "Most outage notices arrive after the fix", b: '3,258 of 5,389 notices (61%) are recorded after the incident ended. The file.ticket gate keeps them out of the queue, but counts of who "noticed" overstate how many people felt the outage.', loc: "outage_notices × incidents · notice delay 117 min vs outages of 42–104 min" },
	{ s: "note", t: "Prompt text: articles and one role label", b: 'Rosters read "a engineer", "a sre", "a account manager". Fiona’s weekend role renders as "a weekend at the cafe", and she works all six days (8,783 decisions, the same as every other cafe worker).', loc: "seed role names → agent.tick wire" },
	{ s: "note", t: "Run provenance is missing", b: 'sim_meta.engine_sha is "unknown", so cassettes, events and decisions cannot be tied to the commit that produced them. Migration 0009 was applied mid-run at 08:17 UTC today.', loc: "sim_meta · schema_migrations" },
	{ s: "note", t: "Dead schema", b: "persons.beliefs (424 rows, all {}) and orgs.policy ({} × 4) are never read or written; commitments has no rows yet.", loc: "py/migrations/0001_world.sql" },
];

const CALLS = [
	["agent.tick", 20753, 148200, 0.8899],
	["cafe.purchase", 15, 23044, 0.0002],
	["payment.timing", 22, 2959, 0.0004],
	["file.ticket", 6, 1428, 0.0001],
	["ticket.answer", 30, 973, 0.0005],
	["ticket.confirm", 6, 768, 0.0001],
	["ticket.triage", 15, 478, 0.0003],
	["credit.decision", 23, 248, 0.0005],
	["catering.order", 5, 183, 0.0001],
	["chase.invoice", 8, 154, 0.0001],
	["payroll.release", 3, 108, 0.0001],
	["close.signoff", 6, 27, 0.0001],
	["episode.round", 4, 6, 0.0001],
] as const;

const MOOD = [
	["ordinary working day", 1.63, 139700],
	["invoicing down", 0.55, 4104],
	["timetrack down", 0.59, 2184],
	["POS down", 0.43, 2692],
] as const;

const OUTAGES = [
	{ name: "POS", esc: 45, not: 90, n: 62, e: 57, te: 16, tk: 93 },
	{ name: "Invoicing", esc: 69, not: 208, n: 51, e: 38, te: 32, tk: 320 },
	{ name: "TimeTrack", esc: 42, not: 605, n: 42, e: 39, te: 12, tk: 65 },
];

const ESCALATED_TO = [
	["Kwame · support", 37, 31.1],
	["Sara · engineer", 32, 44.2],
	["Ingrid · account mgr", 22, 21.1],
	["Tomas · sre", 16, 22.3],
	["Mikel · engineer", 16, 25.2],
	["Ruth · support lead", 10, 5.7],
	["Petra · eng lead", 1, 3.1],
] as const;

const EFFECT_ORDER = [
	"chase.invoice",
	"ticket.confirm",
	"file.ticket",
	"ticket.answer",
	"cafe.purchase",
	"payment.timing",
	"catering.order",
	"credit.decision",
	"close.signoff",
	"payroll.release",
];

const FIRMS: [string, string, string][] = [
	["tallybird.cash", "Tallybird", "--tb"],
	["halloran.cash", "Halloran & Pike", "--hp"],
	["ledgerline.cash", "Ledgerline", "--ll"],
	["thirdrail.cash", "Third Rail", "--tr"],
];


function townData(): TownData {
	const T = D.town;
	const zoneShare: Record<number, number> = {};
	for (const r of D.zones) {
		zoneShare[r.hr] = r.cafe / (r.software_office + r.law_office + r.accounting_office + r.cafe + r.plaza);
	}
	const arrivals: Record<number, number> = {};
	for (const r of D.cafe) arrivals[r.hr] = r.sale + r.walk;
	const people: TownData["people"] = Object.fromEntries(
		D.people.map((p) => [p.person_id, { cafe: +p.cafe_pct, talk: +p.talk_pct, mood: +p.mood }]),
	);
	return {
		tiles: T.tiles.map((row) => [...row].map((c) => T.kinds[c] ?? "grass")),
		cast: T.staff.map((s) => ({ ...s, org_id: s.org })),
		queue: T.queue,
		people,
		cafeShare: zoneShare,
		arrivals,
		topics: [
			["small talk", 0.614],
			["work", 0.243],
			["the outage", 0.106],
			["money", 0.031],
			["other", 0.006],
		],
		// The map at e417422, which the snapshot's tiles were drawn from.
		buildings: [
			{ org_id: "tallybird", zone: "software_office", name: "Tallybird Software", x0: 2, y0: 2, x1: 15, y1: 10, cash: 10690, flag: "payroll held", note: "payroll held since d156" },
			{ org_id: "halloran", zone: "law_office", name: "Halloran & Pike LLP", x0: 24, y0: 2, x1: 37, y1: 10, cash: 76655 },
			{ org_id: "ledgerline", zone: "accounting_office", name: "Ledgerline Accounting", x0: 2, y0: 17, x1: 15, y1: 25, cash: 144562 },
			{ org_id: "thirdrail", zone: "cafe", name: "Third Rail Cafe", x0: 24, y0: 17, x1: 37, y1: 25, cash: 135220 },
		],
		// 14:30–15:15: an illustrative POS outage, raised over coffee.
		outage: { from: 22, to: 25, name: "POS", label: "POS down", shout: "pos is down!" },
		day: "d232 replay",
		cashLabel: "cash at d232",
	};
}

export function Day1InProd() {
	const town = useMemo(townData, []);
	const [hidden, setHidden] = useState<Set<string>>(new Set());

	const cache = useMemo(() => {
		const c = D.cache;
		const raw = c.map((x) => 1 - x.new / x.n);
		const sm = raw.map((_, i) => {
			const w = raw.slice(Math.max(0, i - 6), i + 1);
			return w.reduce((a, b) => a + b, 0) / w.length;
		});
		return { xs: c.map((x) => x.d), sm, j: Math.round(c.length * 0.8) };
	}, []);

	const cashSeries: Series[] = FIRMS.map(([k, name, color]) => ({
		name,
		color,
		values: D.cash[k] ?? [],
		hidden: hidden.has(name),
	}));
	const tb = D.cash["tallybird.cash"] ?? [];
	const hh = D.cash["households.cash"] ?? [];
	const xs = tb.map((_, i) => i);

	const share = D.zones.map((r) => r.cafe / (r.software_office + r.law_office + r.accounting_office + r.cafe + r.plaza));
	const pk = share.indexOf(Math.max(...share));
	const walk = D.cafe.map((r) => r.walk / (r.walk + r.sale));
	const pw = walk.indexOf(Math.max(...walk));

	const names = Object.fromEntries(D.town.staff.map((s) => [s.id, s.name]));
	const people = D.people.map((p) => ({
		id: p.person_id,
		name: names[p.person_id] ?? p.person_id,
		org: p.person_id.split(".")[0] ?? "",
		role: p.role.replace(/_/g, " "),
		mood: +p.mood,
		cafe: +p.cafe_pct,
		talk: +p.talk_pct,
		raised: +p.raised,
		soc: +p.soc,
		dil: +p.dil,
	}));

	return (
		<TipProvider>
			<ReportBar sub="field report · golden-20260920" links={NAV} />
			<div className="page">
				<TownReplay data={town} clock="d232 replay" booksId="economy">
					The simulation's own map (<code>world/map.py</code>): the real desks and walking routes, with all 24 staff
					at their seats. The replay is rebuilt from measured rates, not recorded frames. How often each person heads
					to the cafe follows their share of 148,200 <code>agent.tick</code> decisions, the queue follows cafe
					arrivals by hour, and the speech bubbles use the real topic mix. Hover anyone, or click a building for its
					books.
				</TownReplay>

				<header id="summary" className="summary">
					<Kicker>Field report · production run golden-20260920</Kicker>
					<h1>232 days on one street, for 93 cents</h1>
					<p className="lede">
						What jeve's production database recorded in its first ~40 hours of wall time: four firms, 24 staff, 400
						counterparties, 82,494 events and 202,934 typed decisions. The mechanics hold up. The economy, and what
						the agents can perceive, do not yet.
					</p>
					<div className="status">
						<span>
							<b>d232</b>
						</span>
						<span>tick 8,764</span>
						<span>seq 82,494</span>
						<span className="badge b-good">● running · lag 0 s</span>
						<span className="badge b-mark">jev-1.13-20260917</span>
						<span>snapshot 2026-09-23 08:48 UTC · read-only</span>
					</div>

					<div className="vitals">
						<Vital n="232" unit="sim-days">
							in ~40 wall hours; nights and Sundays are skipped
						</Vital>
						<Vital n="202,934">typed decisions: 88% from Jev, 12% settled free by a gate</Vital>
						<Vital n="$0.93">real spend on OpenRouter's meter; the local ledger says $0.97</Vital>
						<Vital n="88%">of Jev decisions served from cache: 20,896 distinct calls in all</Vital>
						<Vital n="5 / 33" alert>
							weeks Tallybird met payroll, and none since day 156
						</Vital>
						<Vital n="86%">of outages escalated in person, 84% of those over coffee</Vital>
					</div>

					<Say by="the short version">
						Typed decisions carry the simulation. Movement, buying, paying, triage and credits all come from Jev, the
						cost is negligible, and the double-entry ledger balances to the cent. The gaps are in what agents{" "}
						<em>perceive</em>. No one knows Tallybird hasn't paid its staff for eleven weeks. Conversations move no
						information. Most choices follow a temperament word far more than the situation.
					</Say>
				</header>

				<section id="findings">
					<Kicker>Key findings</Kicker>
					<h2>Twenty-one findings</h2>
					<p className="sub">
						Each claim was checked against the database or the source; the last line of every card is the evidence.
					</p>
					<Findings items={FINDINGS} cats={CATS} storageKey="jeve-f" />
				</section>

				<section id="run">
					<Kicker>The run</Kicker>
					<h2>Cheap, fast, and almost entirely one question</h2>
					<p className="sub">
						The daemon has run since 2026-09-21 16:55 UTC with no recorded error, covering about 5.8 sim-days per wall
						hour.
					</p>
					<div className="stack">
						<Fig
							title="Cache hit rate by sim-day"
							legend="7-day mean"
							caption={
								<>
									Share of Jev decisions answered by an existing call. It climbs from 71% to about 90% and then
									flattens: after day 200 the cache still adds ~100 new contexts a day, nearly all of them{" "}
									<code>agent.tick</code>.
								</>
							}
						>
							<LineChart
								series={[{ name: "hit rate", color: "--mark", values: cache.sm }]}
								xs={cache.xs}
								yMin={0.6}
								yTicks={[0.6, 0.7, 0.8, 0.9, 1]}
								area
								h={250}
								yfmt={(v) => `${Math.round(v * 100)}%`}
								xfmt={dayfmt}
								aria="Cache hit rate by sim-day"
								notes={[
									{ i: 3, v: cache.sm[3] ?? 0, text: "71% on day 0" },
									{ i: cache.j, v: cache.sm[cache.j] ?? 0, text: "still ~100 new contexts/day" },
								]}
							/>
						</Fig>
						<Fig
							title="Where the calls went"
							legend="13 question sets"
							caption={
								<>
									<code>agent.tick</code> accounts for 99.3% of calls and 99.9% of cost. The other twelve sets behave
									like lookup tables: all non-tick behaviour in the town comes from 149 calls.
								</>
							}
						>
							<CallsTable rows={CALLS.map(([set, calls, decisions, usd]) => ({ set, calls, decisions, usd }))} />
						</Fig>
					</div>
					<Callout
						title={
							<>
								Why <code>agent.tick</code> is different:
							</>
						}
					>
						the <code>who_is_here</code> roster is part of its prompt. Without the roster there are 615 distinct
						states; with it, 20,826. That is a 34× blow-up, and it is almost the whole bill.
					</Callout>
				</section>

				<section id="economy">
					<Kicker>The economy</Kicker>
					<h2>A software firm that can't make payroll, and wages that never come back</h2>
					<p className="sub">
						Cash on hand at the end of each sim-day, from 85,232 ledger entries that sum to exactly zero. Click a firm
						in the legend to hide it.
					</p>
					<Fig
						title="Cash by firm"
						legend={<SeriesToggle series={cashSeries} hidden={hidden} onChange={setHidden} />}
						caption="Tallybird falls from $48k to under $10k by day 30, bottoms at $619 on day 157, sends 151 insolvency warnings, and runs payroll 5 times. Third Rail rises in a straight line because its 100 outside customers are paid for from outside the model."
					>
						<LineChart
							series={cashSeries}
							xs={xs}
							endLabels
							h={330}
							yfmt={dollars}
							xfmt={dayfmt}
							aria="Cash by firm over 232 sim-days"
							vlines={[156]}
							notes={[{ i: 156, v: tb[156] ?? 0, text: "last payroll · d156" }]}
						/>
					</Fig>
					<div className="grid2 mt">
						<Fig
							title="Tallybird, per month"
							caption="Subscription revenue (100 outside subscribers at ~$49, plus five seats sold to the other firms) against the payroll the seed gives it. An 11× gap is a calibration problem, not bad luck."
						>
							<ColChart
								cats={["subscriptions", "seats to firms", "payroll owed"]}
								values={[4900, 810, 63270]}
								colors={["--tb", "--tb", "--bad"]}
								hatch={2}
								ticks={[0, 20000, 40000, 60000, 80000]}
								h={260}
								mt={28}
								yfmt={(v) => `$${Math.round(v / 1000)}k`}
								valLabels={["$4.9k", "$0.8k", "$63.3k"]}
								aria="Tallybird monthly revenue against payroll"
								tipf={(i) =>
									[
										<>
											<b>subscriptions</b>
											<div className="m">100 outside subscribers, avg $49/mo</div>
										</>,
										<>
											<b>seats to firms</b>
											<div className="m">five module seats, $810/mo</div>
										</>,
										<>
											<b>payroll owed</b>
											<div className="m">$14,600/week × 52 ÷ 12</div>
										</>,
									][i]
								}
							/>
						</Fig>
						<Fig
							title="Household cash"
							caption="Of $759k paid in wages, $10.6k (1.4%) came back as spending. The circular flow doesn't close, so demand in this economy comes from outside it."
						>
							<LineChart
								series={[{ name: "household cash", color: "--sand", values: hh }]}
								xs={xs}
								area
								h={260}
								mt={36}
								yfmt={(v) => `$${Math.round(v / 1000)}k`}
								xfmt={dayfmt}
								aria="Household cash over 232 sim-days"
								notes={[{ i: 176, v: hh[176] ?? 0, text: "98.6% of wages saved" }]}
							/>
						</Fig>
					</div>
					<Callout title="Collections work.">
						1,059 invoices were paid, 2.06 days late on average and never more than 25. Nothing is overdue at the
						snapshot and nothing was written off. The slowest fifth of payers average 3.7 days late, the fastest 0.5;
						being chased raises the chance of paying that day by 0.1–0.17.
					</Callout>
				</section>

				<section id="people">
					<Kicker>The people</Kicker>
					<h2>A believable day, and personality as a constant</h2>
					<p className="sub">
						148,200 <code>agent.tick</code> decisions: every staff member, every open tick, asked where to go, what
						mood they're in, and whether to talk.
					</p>
					<div className="grid2">
						<Fig
							title="Office staff at the cafe"
							legend="share of decisions, by hour"
							caption="From 3% at 09:00 to 31% at 13:00: a lunch rhythm that no rule wrote. The plaza was chosen 34 times in 148,200."
						>
							<ColChart
								cats={D.zones.map((r) => pad2(r.hr))}
								values={share}
								color="--tr"
								ticks={[0, 0.1, 0.2, 0.3, 0.4]}
								h={250}
								yfmt={(v) => `${Math.round(v * 100)}%`}
								aria="Share of office staff at the cafe by hour"
								notes={[{ i: pk, text: `lunch · ${Math.round((share[pk] ?? 0) * 100)}%` }]}
								tipf={(i) => (
									<>
										<b>{pad2(D.zones[i]?.hr ?? 0)}:00</b>
										<TipRow label="at the cafe">{((share[i] ?? 0) * 100).toFixed(1)}%</TipRow>
									</>
								)}
							/>
						</Fig>
						<Fig
							title="Cafe walkouts"
							legend="share of arrivals, by hour"
							caption="Walkouts track the line. 07:00 and 17:00 read zero because nobody queues then, so those arrivals are settled by the no-line gate and never reach the model."
						>
							<ColChart
								cats={D.cafe.map((r) => pad2(r.hr))}
								values={walk}
								color="--tr"
								ticks={[0, 0.1, 0.2, 0.3, 0.4]}
								h={250}
								yfmt={(v) => `${Math.round(v * 100)}%`}
								aria="Cafe walkout rate by hour"
								notes={[{ i: pw, text: `noon rush · ${Math.round((walk[pw] ?? 0) * 100)}%` }]}
								tipf={(i) => (
									<>
										<b>{pad2(D.cafe[i]?.hr ?? 0)}:00</b>
										<TipRow label="walkout rate">{((walk[i] ?? 0) * 100).toFixed(1)}%</TipRow>
										<TipRow label="sales">{fmt(D.cafe[i]?.sale ?? 0)}</TipRow>
										<TipRow label="walkouts">{fmt(D.cafe[i]?.walk ?? 0)}</TipRow>
									</>
								)}
							/>
						</Fig>
					</div>
					<Fig
						title="Mood by what's on their mind"
						legend="mean on a 0–3 scale"
						className="mt"
						caption={
							<>
								The prompt's <code>on_their_mind</code> field takes four values, and 93% of calls say "an ordinary
								working day". Outages are the only input that moves mood. Unpaid wages, firm cash and insolvency never
								reach the prompt.
							</>
						}
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
						title="All 24 staff"
						legend="click a column to sort"
						className="mt"
						caption="Mood is argmax-sampled (J mode), so it barely moves: 18 of 24 staff have a standard deviation of 0.4 or less. Across these 24 people, sociability tracks talk rate (r = 0.63), diligence tracks mood (r = 0.62), and diligent office staff visit the cafe less (r = −0.58)."
					>
						<PeopleTable rows={people} />
					</Fig>
				</section>

				<section id="model">
					<Kicker>What moves the model</Kicker>
					<h2>The temperament word outweighs the situation</h2>
					<p className="sub">
						For each question set, the widest swing in Jev's probability as one input changes, averaged over the rest
						(main-effect range, 0–1). Violet inputs describe who the person is; sand ones describe their situation.
					</p>
					<Fig
						caption={`"How likely is this person to…" questions (chase, file, confirm, answer) answer mostly to temperament. How long an outage has lasted changes the chance of filing a ticket by 0.04; a ticket's age changes confirmation by 0.007. Judgement questions do follow the situation: credit tracks outage length (0.84), month-end sign-off tracks overdue bills (0.67), payroll release tracks timesheets (0.78).`}
					>
						<WhoLegend />
						<Effects effects={D.effects} order={EFFECT_ORDER} />
					</Fig>
					<AnswerTables tables={D.lookup} initial="payment.timing" storageKey="jeve-lt" />
					<Callout title="One non-monotone pattern.">
						A client who "pays the moment it falls due" pays with probability 0.90 on the due day, but only 0.43 once
						the bill is more than a week late: the model reads lateness as a sign they've decided not to pay. Habitual
						late payers stay flat at 0.18–0.26 whatever the due date.
					</Callout>
				</section>

				<section id="outages">
					<Kicker>Outages and escalation</Kicker>
					<h2>The real help desk is the coffee line</h2>
					<p className="sub">
						155 incidents, 478 tickets, 134 escalations. Escalation happens face to face, and usually before the ticket
						queue matters.
					</p>
					<div className="grid2">
						<Fig
							title="Outage length, minutes"
							legend={<EscLegend />}
							caption="Escalation arrives 12–32 minutes in and at least halves an outage. Un-escalated means include outages that ran over a skipped night (up to 870 min). The average subscriber notices at 117 minutes, so 61% of notices come in after the fix."
						>
							<Dumbbell
								rows={OUTAGES}
								ticks={[0, 150, 300, 450, 600]}
								max={650}
								tipf={(i) => {
									const r = OUTAGES[i];
									if (!r) return null;
									return (
										<>
											<b>{r.name}</b>
											<TipRow label="incidents">{r.n}</TipRow>
											<TipRow label="escalated">
												{r.e} ({Math.round((r.e / r.n) * 100)}%)
											</TipRow>
											<TipRow label="minutes to escalate">{r.te}</TipRow>
											<TipRow label="mean length, escalated">{r.esc} min</TipRow>
											<TipRow label="mean length, not">{r.not} min</TipRow>
											<TipRow label="tickets">{r.tk}</TipRow>
										</>
									);
								}}
							/>
						</Fig>
						<Fig
							title="Who got escalated to"
							legend="escalations received"
							caption="Escalations land on whoever from Tallybird is in the cafe, not on whoever owns the fix. Kwame (support, 31% of ticks at the cafe) and Sara (engineer, 44%) took 69 of 134. Petra, the eng lead, is at the cafe 3% of the time and took one."
						>
							<BarChart
								cats={ESCALATED_TO.map((e) => e[0])}
								values={ESCALATED_TO.map((e) => e[1])}
								color="--tb"
								rowH={28}
								fmt={(v) => String(v)}
								aria="Escalations received by Tallybird staff"
								tipf={(i) => (
									<>
										<b>{ESCALATED_TO[i]?.[0]}</b>
										<TipRow label="escalations received">{ESCALATED_TO[i]?.[1]}</TipRow>
										<TipRow label="ticks at the cafe">{ESCALATED_TO[i]?.[2]}%</TipRow>
									</>
								)}
							/>
						</Fig>
					</div>
					<Callout title="Conversation moves no information.">
						15,988 encounters, 1,773 of them about an outage, yet 3,370 of 3,371 knowledge rows are first-hand. The
						one relayed fact came from the single episode that has run since episodes were deployed at 08:17 UTC today.
					</Callout>
				</section>

				<section id="defects">
					<Kicker>Defects</Kicker>
					<h2>Found in the data, confirmed in the code</h2>
					<p className="sub">Each shows up in production rows and traces to a line of source.</p>
					<Defects items={DEFECTS} />
				</section>

				<section id="next">
					<Kicker>Recommendations</Kicker>
					<h2>What to change next, in order</h2>
					<p className="sub">Ordered by how much each one distorts the research question.</p>
					<ol className="recs">
						<li>
							<b>Make insolvency matter, then recalibrate Tallybird.</b>
							<span>
								An unpaid team works, lunches and orders large catering as usual. Add consequences (late pay in{" "}
								<code>on_their_mind</code>, departures, a price rise travelling as a <code>price_rise:&lt;org&gt;</code>{" "}
								fact), then set prices or headcount so the firm can plausibly survive.
							</span>
						</li>
						<li>
							<b>Close the household loop.</b>
							<span>
								Tie household spending to income, and fund cafe customers from households rather than from outside
								the model. Until then wages drain one way and any GDP-style measure is meaningless.
							</span>
						</li>
						<li>
							<b>Put the economy into perception.</b>
							<span>
								Widen <code>on_their_mind</code> beyond its four states (late pay, a lean month, a lost client) so
								mood has more than one lever.
							</span>
						</li>
						<li>
							<b>Canonicalise the roster.</b>
							<span>
								Sort <code>who_is_here</code> and collapse it to role counts, or cap it at the three most relevant
								people. That pulls <code>agent.tick</code> from 20,826 contexts back toward 615, and the hit rate
								into the high 90s.
							</span>
						</li>
						<li>
							<b>
								Ask <code>agent.tick</code> only when something changed.
							</b>
							<span>
								Every office worker has answered it 5,331 times, and 89% of those answers end in no encounter.
								Asking only on a change, or hourly by default, should roughly halve the calls.
							</span>
						</li>
						<li>
							<b>Fix the defects above</b>
							<span>
								before episode data piles up. Autopay and provenance corrupt measurements the research question
								depends on.
							</span>
						</li>
						<li>
							<b>Give "how likely" questions a situation that matters.</b>
							<span>
								Where temperament dominates, make duration, size and age concrete ("down six hours, at month-end")
								and check that the main-effect range moves.
							</span>
						</li>
						<li>
							<b>Stamp the engine SHA.</b>
							<span>
								<code>sim_meta.engine_sha</code> reads "unknown", so this run can't be tied to a commit.
							</span>
						</li>
					</ol>

					<Kicker className="spaced">Method</Kicker>
					<ul className="method">
						<li>
							All queries ran against production Postgres via Doppler (<code>worker/prd</code>) with{" "}
							<code>default_transaction_read_only=on</code> forced per session. Nothing was written.
						</li>
						<li>
							Snapshot taken 08:40–08:48 UTC while the daemon kept running, so some counts drift by tens of rows
							between queries (model calls went from 20,896 to 20,969).
						</li>
						<li>
							Main-effect ranges are spreads of mean probability over the cached contexts actually sampled. That is
							not a controlled design, so read them as a ranking.
						</li>
						<li>Correlations across staff use n = 24 and are descriptive.</li>
						<li>
							Semantics (gates, modes, trait tertiles, night skipping) and the town map come from the source at
							commit <code>e417422</code>.
						</li>
					</ul>
					<SiteFooter>
						<span>jeve · run golden-20260920 · root seed 20260920</span>
						<span>report generated 2026-09-23</span>
					</SiteFooter>
				</section>
			</div>
		</TipProvider>
	);
}
