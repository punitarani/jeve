/**
 * What the live report says about the numbers it is handed.
 *
 * The first report's findings were written by someone reading a snapshot. The
 * live one cannot wait for that, so its findings are rules over /report: each
 * the same question the first report asked (do the books balance? does
 * every firm make payroll? does talk move information?) with a threshold
 * standing in for the reader's judgement. Pure functions of the payload, so
 * the page is only layout.
 */
import type { FieldReport, TownMap } from "@jeve/contracts";
import { fmt, pct, usd } from "./format";
import type { Finding, Severity } from "./parts";
import type { TownData } from "./town";

/** Spend in words for a headline: "93 cents", "$4.12", or "nothing". */
export function spendWords(spend: number): string {
	if (spend <= 0) return "nothing";
	if (spend < 1) return `${Math.max(1, Math.round(spend * 100))} cents`;
	return `$${spend.toFixed(2)}`;
}

export const ORG_COLOR: Record<string, string> = {
	tallybird: "--tb",
	halloran: "--hp",
	ledgerline: "--ll",
	thirdrail: "--tr",
};
export const ORG_SHORT: Record<string, string> = {
	tallybird: "Tallybird",
	halloran: "Halloran & Pike",
	ledgerline: "Ledgerline",
	thirdrail: "Third Rail",
};

export type PayrollStanding = FieldReport["payroll"][number] & {
	/** Runs the best-paying firm has made: the town's payroll rhythm so far. */
	due: number;
	/** Missed the most recent run somebody else made. */
	behind: boolean;
};

/**
 * Payroll against the town's own rhythm. Every firm pays weekly, so the most
 * runs any firm has made is how many were due; a firm whose last run is older
 * than everyone else's latest has missed at least the latest one.
 */
export function payrollStandings(r: FieldReport): PayrollStanding[] {
	const due = Math.max(0, ...r.payroll.map((p) => p.paid));
	const latest = Math.max(-1, ...r.payroll.map((p) => p.last_paid_day ?? -1));
	return r.payroll.map((p) => ({
		...p,
		due,
		behind: due > 0 && p.paid < due && (p.last_paid_day ?? -1) < latest,
	}));
}

/** The firm furthest behind on payroll, if any is. */
export function weakest(r: FieldReport): PayrollStanding | null {
	const behind = payrollStandings(r).filter((p) => p.behind);
	return behind.sort((a, b) => a.paid - b.paid)[0] ?? null;
}

const cashOf = (r: FieldReport, org: string) =>
	r.cash.series.find((s) => s.org_id === org)?.values.at(-1) ?? 0;

/** The live findings, most severe first. */
export function liveFindings(r: FieldReport): Finding[] {
	const v = r.vitals;
	const out: Finding[] = [];
	const add = (c: string, s: Severity, t: string, b: string, e: string) => out.push({ c, s, t, b, e });

	if (v.ledger_imbalance_cents === 0) {
		add("economy", "good", "The books balance", `${fmt(v.ledger_entries)} ledger entries sum to exactly zero.`, "SUM(ledger_entries.amount_cents) = 0");
	} else {
		add(
			"economy",
			"critical",
			"The books do not balance",
			`${fmt(v.ledger_entries)} ledger entries sum to ${usd(v.ledger_imbalance_cents)}, not zero. Money was created or lost somewhere.`,
			`SUM(ledger_entries.amount_cents) = ${v.ledger_imbalance_cents}`,
		);
	}

	const standings = payrollStandings(r);
	const behind = standings.filter((p) => p.behind);
	for (const p of behind) {
		const ratio = p.paid / Math.max(1, p.due);
		add(
			"economy",
			ratio < 0.5 ? "critical" : "high",
			`${ORG_SHORT[p.org_id] ?? p.name} is missing payroll`,
			`Paid ${p.paid} of ${p.due} payroll runs${p.last_paid_day === null ? ", none yet" : `, the last on day ${p.last_paid_day}`}, with ${usd(cashOf(r, p.org_id))} on hand and ${p.insolvency_warnings} insolvency warnings.`,
			`payroll.paid ${p.org_id} n=${p.paid}; payroll.held n=${p.held}`,
		);
	}
	if (behind.length === 0 && standings.some((p) => p.due > 0)) {
		add("economy", "good", "Every firm makes payroll", `All ${standings.length} firms have paid every payroll run so far.`, `payroll.paid per firm: ${standings.map((p) => p.paid).join(" / ")}`);
	}

	const h = r.households;
	if (h.wages_cents > 0) {
		const back = h.spending_cents / h.wages_cents;
		add(
			"economy",
			back < 0.2 ? "high" : "good",
			back < 0.2 ? "Households are a sink, not a sector" : "Wages come back",
			`Of ${usd(h.wages_cents)} paid in wages, ${usd(h.spending_cents)} (${pct(back, 1)}) came back as spending.`,
			"households.income vs households.spending",
		);
	}

	const c = r.collections;
	if (c.paid > 0) {
		add(
			"economy",
			c.overdue === 0 ? "good" : c.overdue > 10 ? "high" : "note",
			c.overdue === 0 ? "Bills get paid" : `${fmt(c.overdue)} invoices are overdue`,
			`${fmt(c.paid)} payments, ${c.mean_days_late?.toFixed(2) ?? "0"} days late on average and never more than ${c.max_days_late ?? 0}. ${c.overdue === 0 ? "Nothing is overdue" : `${fmt(c.overdue)} of ${fmt(c.open)} open invoices are past due`}${c.written_off ? `, and ${fmt(c.written_off)} were written off` : ""}.`,
			"payments · invoices where paid_sim is null",
		);
	}

	const minds = r.mood_by_mind;
	const ordinary = minds.find((m) => m.mind === "ordinary");
	const outages = minds.filter((m) => m.mind !== "ordinary" && m.mind !== "other");
	const mindTotal = minds.reduce((a, m) => a + m.decisions, 0);
	if (ordinary && outages.length && mindTotal) {
		const worst = outages.reduce((a, b) => (b.mood < a.mood ? b : a));
		add(
			"behaviour",
			ordinary.decisions / mindTotal > 0.9 ? "high" : "note",
			"Only outages move mood",
			`What is on their mind takes ${minds.length} values, and ${pct(ordinary.decisions / mindTotal)} of calls say an ordinary day. Mean mood is ${ordinary.mood.toFixed(2)} then, and ${worst.mood.toFixed(2)} with ${r.outages.find((o) => o.module_id === worst.mind)?.name ?? worst.mind} down.`,
			"agent.tick request state.on_their_mind",
		);
	}

	if (v.incidents > 0) {
		add(
			"behaviour",
			"high",
			v.incidents_escalated / v.incidents > 0.5 ? "Escalation is social, not procedural" : "Most outages wait for the queue",
			`${fmt(v.incidents_escalated)} of ${fmt(v.incidents)} incidents were escalated in person${v.escalations ? `, ${pct(v.escalations_in_cafe / v.escalations)} of escalations in the cafe` : ""}.`,
			"incidents.escalated_sim · ticket.escalated payload.zone",
		);
	}

	const k = r.knowledge;
	const known = k.first_hand + k.relayed;
	if (known > 0) {
		const relayed = k.relayed / known;
		add(
			"behaviour",
			relayed < 0.05 ? "high" : "good",
			relayed < 0.05 ? "Talk moves little" : "News travels",
			`${fmt(k.encounters)} encounters; ${fmt(k.relayed)} of ${fmt(known)} knowledge rows (${pct(relayed, 1)}) were passed on rather than seen first-hand.`,
			`knowledge.hops: 0 → ${fmt(k.first_hand)} · >0 → ${fmt(k.relayed)}`,
		);
	}

	if (v.modelled > 0) {
		const last = r.cache_by_day.slice(-7);
		const newPerDay = last.reduce((a, d) => a + d.new_calls, 0) / Math.max(1, last.length);
		add(
			"architecture",
			v.cache_hit_rate >= 0.9 ? "good" : "note",
			`The cache answers ${pct(v.cache_hit_rate)}`,
			`${fmt(v.distinct_calls)} distinct calls served ${fmt(v.modelled)} modelled decisions. The last week still minted ${fmt(newPerDay)} new contexts a day.`,
			"1 − distinct model_call / modelled decisions",
		);
		const tick = r.calls.find((x) => x.question_set === "agent.tick");
		const calls = r.calls.reduce((a, x) => a + x.calls, 0);
		const cost = r.calls.reduce((a, x) => a + x.usd, 0);
		if (tick && calls && tick.calls / calls > 0.8) {
			add(
				"architecture",
				"high",
				"One question is the whole bill",
				`agent.tick is ${pct(tick.calls / calls, 1)} of distinct calls${cost ? ` and ${pct(tick.usd / cost, 1)} of cost` : ""}: its prompt carries who is in the room, so every new crowd is a new call.`,
				`agent.tick: ${fmt(tick.calls)} calls of ${fmt(calls)}`,
			);
		}
	}
	const gated = r.calls.reduce((a, x) => a + x.gated, 0);
	if (v.decisions > 0 && gated > 0) {
		add(
			"architecture",
			"note",
			"Gates are free and do real work",
			`${fmt(gated)} decisions (${pct(gated / v.decisions)}) were settled by a gate without a model call.`,
			"decisions where model_call is null",
		);
	}

	const rank: Record<Severity, number> = { critical: 0, high: 1, note: 2, good: 3 };
	return out.sort((a, b) => rank[a.s] - rank[b.s]);
}

export const LIVE_CATS: [string, string, string][] = [
	["all", "all", "all"],
	["economy", "economy", "economy"],
	["behaviour", "agent behaviour", "agent behaviour"],
	["architecture", "architecture", "architecture"],
];

/** Topic keys as the town's bubbles say them. */
const topicWords = (t: string) => t.replace(/^the_/, "the ").replace(/_/g, " ");

/** The town replay's inputs, from the live report and the static map. */
export function liveTown(r: FieldReport, map: TownMap): TownData {
	const people: TownData["people"] = Object.fromEntries(
		r.people.map((p) => [p.id, { cafe: p.cafe_share * 100, talk: p.talk_share * 100, mood: p.mood ?? 0 }]),
	);
	const topicTotal = r.topics.reduce((a, t) => a + t.n, 0);
	const standings = payrollStandings(r);
	const buildings: TownData["buildings"] = Object.fromEntries(
		Object.keys(ORG_COLOR).map((org) => {
			const p = standings.find((s) => s.org_id === org);
			return [
				org,
				{
					cash: cashOf(r, org) / 100,
					...(p?.behind
						? {
								flag: "payroll held",
								note: p.last_paid_day === null ? "no payroll yet" : `payroll held since d${p.last_paid_day}`,
							}
						: {}),
				},
			];
		}),
	);
	// Illustrate the module that goes down most, if any has.
	const worst = r.outages.filter((o) => o.incidents > 0).sort((a, b) => b.incidents - a.incidents)[0];
	return {
		tiles: map.tiles,
		cast: r.cast,
		queue: r.queue,
		people,
		cafeShare: Object.fromEntries(r.office_at_cafe.map((h) => [h.hour, h.share])),
		arrivals: Object.fromEntries(r.cafe_by_hour.map((h) => [h.hour, h.sales + h.walkouts])),
		topics: topicTotal ? r.topics.map((t) => [topicWords(t.topic), t.n / topicTotal] as const) : [],
		buildings,
		outage: worst
			? { from: 22, to: 25, name: worst.name, label: `${worst.name} down`, shout: `${worst.module_id} is down!` }
			: null,
		day: `d${r.clock.day} replay`,
		cashLabel: `cash at d${r.clock.day}`,
	};
}

/** A trailing mean over `window` points, as the cache chart smooths its days. */
export function trailingMean(values: number[], window = 7): number[] {
	return values.map((_, i) => {
		const w = values.slice(Math.max(0, i - window + 1), i + 1);
		return w.reduce((a, b) => a + b, 0) / w.length;
	});
}
