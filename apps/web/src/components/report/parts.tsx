"use client";

/**
 * The pieces a field report is assembled from, other than its charts and its
 * town. Each is the first report's markup (reports/day-1-in-prod) with the
 * data made a prop, so a frozen report and the live one render through the
 * same components and cannot drift apart in look.
 */
import Link from "next/link";
import { type ReactNode, useEffect, useState } from "react";
import { Dot } from "./charts";
import { fmt } from "./format";

export { fmt };

/** Reads a per-viewer preference; storage can be absent or refuse. */
function remembered(key: string): string | null {
	try {
		return localStorage.getItem(key);
	} catch {
		return null;
	}
}
function remember(key: string, value: string) {
	try {
		localStorage.setItem(key, value);
	} catch {
		// A private window: the choice just isn't kept.
	}
}

/** The sticky app bar: the logo home, what this is, and a scroll-spied table of contents. */
export function ReportBar({ sub, links }: { sub: ReactNode; links: [string, string][] }) {
	const [on, setOn] = useState(0);
	useEffect(() => {
		const sections = links.map(([id]) => document.getElementById(id));
		const spy = () => {
			let i = 0;
			sections.forEach((s, k) => {
				if (s && s.getBoundingClientRect().top < 120) i = k;
			});
			setOn(i);
		};
		addEventListener("scroll", spy, { passive: true });
		spy();
		return () => removeEventListener("scroll", spy);
	}, [links]);
	return (
		<header className="bar">
			<div className="bar-in">
				<Link href="/" className="logo">
					jeve
				</Link>
				<span className="sub">{sub}</span>
				<nav aria-label="Sections">
					{links.map(([id, label], k) => (
						<a key={id} href={`#${id}`} className={k === on ? "on" : undefined}>
							{label}
						</a>
					))}
				</nav>
			</div>
		</header>
	);
}

export function Kicker({ children, className }: { children: ReactNode; className?: string }) {
	return <div className={className ? `kicker ${className}` : "kicker"}>{children}</div>;
}

export function Vital({
	n,
	unit,
	alert,
	children,
}: {
	n: ReactNode;
	unit?: string;
	alert?: boolean;
	children: ReactNode;
}) {
	return (
		<div className={alert ? "vital alert" : "vital"}>
			<div className="n">
				{n}
				{unit && <small>{unit}</small>}
			</div>
			<div className="l">{children}</div>
		</div>
	);
}

/** A thesis, set as the sim's own speech bubble. */
export function Say({ by, children }: { by: string; children: ReactNode }) {
	return (
		<>
			<div className="say">
				<p>{children}</p>
			</div>
			<div className="say-by">{by}</div>
		</>
	);
}

export function Callout({ title, children }: { title: ReactNode; children: ReactNode }) {
	return (
		<div className="callout">
			<b>{title}</b> {children}
		</div>
	);
}

export function Fig({
	title,
	legend,
	caption,
	className,
	children,
}: {
	title?: string;
	legend?: ReactNode;
	caption?: ReactNode;
	className?: string;
	children: ReactNode;
}) {
	return (
		<figure className={className}>
			{(title || legend) && (
				<div className="fh">
					{title && <h3>{title}</h3>}
					{typeof legend === "string" ? <span className="legend">{legend}</span> : legend}
				</div>
			)}
			{children}
			{caption && <figcaption>{caption}</figcaption>}
		</figure>
	);
}

export type Severity = "critical" | "high" | "note" | "good";
export const SEV: Record<Severity, [string, string]> = {
	critical: ["b-bad", "▲ critical"],
	high: ["b-warn", "◆ significant"],
	note: ["b-mark", "● note"],
	good: ["b-good", "✓ works"],
};

export function Sev({ s }: { s: Severity }) {
	return <span className={`badge ${SEV[s][0]}`}>{SEV[s][1]}</span>;
}

export type Finding = {
	/** Category key. */
	c: string;
	s: Severity;
	/** Title, body, and the evidence line. */
	t: string;
	b: string;
	e: string;
};

/** Filter chips and a grid of finding cards; the chosen filter is remembered per viewer. */
export function Findings({
	items,
	cats,
	storageKey,
}: {
	items: Finding[];
	/** [key, chip label, card label], "all" first. */
	cats: [string, string, string][];
	storageKey: string;
}) {
	const [f, setF] = useState("all");
	useEffect(() => {
		const saved = remembered(storageKey);
		if (saved && cats.some(([k]) => k === saved)) setF(saved);
	}, [storageKey, cats]);
	const label = Object.fromEntries(cats.map(([k, , card]) => [k, card]));
	return (
		<>
			<div className="filters" role="group" aria-label="Filter findings">
				{cats.map(([k, chip]) => (
					<button
						key={k}
						className="fchip"
						type="button"
						aria-pressed={f === k}
						onClick={() => {
							setF(k);
							remember(storageKey, k);
						}}
					>
						{chip}
						<i>{k === "all" ? items.length : items.filter((x) => x.c === k).length}</i>
					</button>
				))}
			</div>
			<div className="findings" data-testid="findings">
				{items
					.filter((x) => f === "all" || x.c === f)
					.map((x) => (
						<article className="f" key={x.t}>
							<div className="tags">
								<Sev s={x.s} />
								<span className="cat">{label[x.c]}</span>
							</div>
							<h3>{x.t}</h3>
							<p>{x.b}</p>
							<div className="evd">{x.e}</div>
						</article>
					))}
			</div>
		</>
	);
}

export type Defect = { s: Severity; t: string; b: string; loc: string };

export function Defects({ items }: { items: Defect[] }) {
	return (
		<div className="defects">
			{items.map((d) => (
				<div className="d" key={d.t}>
					<Sev s={d.s} />
					<div>
						<h3>{d.t}</h3>
						<p>{d.b}</p>
						<div className="loc">{d.loc}</div>
					</div>
				</div>
			))}
		</div>
	);
}

export type CallRow = { set: string; calls: number; decisions: number; usd: number };

/** Where the calls went: decisions per distinct call, on a log bar. */
export function CallsTable({ rows }: { rows: CallRow[] }) {
	const per = (r: CallRow) => (r.calls ? r.decisions / r.calls : 0);
	const maxR = Math.max(1, ...rows.map(per));
	return (
		<div className="tbl">
			<table>
				<thead>
					<tr>
						<th>question set</th>
						<th className="n">distinct calls</th>
						<th className="n">Jev decisions</th>
						<th>decisions per call</th>
						<th className="n">cost</th>
					</tr>
				</thead>
				<tbody>
					{rows.map((r) => {
						const p = per(r);
						return (
							<tr key={r.set}>
								<td>{r.set}</td>
								<td className="n">{fmt(r.calls)}</td>
								<td className="n">{fmt(r.decisions)}</td>
								<td>
									<span
										className="mbar"
										style={{
											width: Math.max(2, (Math.log10(p + 1) / Math.log10(maxR + 1)) * 150),
											background: "var(--mark)",
										}}
									/>
									{p < 10 ? p.toFixed(1) : fmt(p)}
								</td>
								<td className="n">${r.usd.toFixed(4)}</td>
							</tr>
						);
					})}
				</tbody>
			</table>
		</div>
	);
}

export type PersonRow = {
	id: string;
	name: string;
	org: string;
	role: string;
	mood: number;
	cafe: number;
	talk: number;
	raised: number;
	soc: number;
	dil: number;
};
type PersonKey = Exclude<keyof PersonRow, "id" | "org" | "role">;
const PEOPLE_COLS: [PersonKey, string][] = [
	["name", "person"],
	["mood", "mean mood"],
	["cafe", "at the cafe"],
	["talk", "stops to talk"],
	["raised", "raised outage"],
	["soc", "sociability"],
	["dil", "diligence"],
];
const ORG_COLOR: Record<string, string> = {
	tallybird: "--tb",
	halloran: "--hp",
	ledgerline: "--ll",
	thirdrail: "--tr",
};

/** Every member of staff; click (or Enter on) a column to sort by it. */
export function PeopleTable({ rows }: { rows: PersonRow[] }) {
	const [key, setKey] = useState<PersonKey>("talk");
	const [asc, setAsc] = useState(false);
	const sorted = rows.slice().sort((a, b) => (a[key] > b[key] ? 1 : a[key] < b[key] ? -1 : 0) * (asc ? 1 : -1));
	const sortBy = (k: PersonKey) => {
		if (k === key) setAsc(!asc);
		else {
			setKey(k);
			setAsc(k === "name");
		}
	};
	return (
		<div className="tbl tbl-people" data-testid="people">
			<table>
				<thead>
					<tr>
						{PEOPLE_COLS.map(([k, label], i) => (
							<th
								key={k}
								data-k={k}
								tabIndex={0}
								className={[i ? "n" : "", k === key ? (asc ? "sorted asc" : "sorted") : ""].join(" ").trim() || undefined}
								aria-sort={k === key ? (asc ? "ascending" : "descending") : "none"}
								onClick={() => sortBy(k)}
								onKeyDown={(e) => {
									if (e.key === "Enter" || e.key === " ") {
										e.preventDefault();
										sortBy(k);
									}
								}}
							>
								{label}
							</th>
						))}
					</tr>
				</thead>
				<tbody>
					{sorted.map((p) => (
						<tr key={p.id}>
							<td>
								<div className="who">
									<b>
										<i className="dot who-dot" style={{ background: `var(${ORG_COLOR[p.org] ?? "--dim"})` }} />
										{p.name}
									</b>
									<span>
										{p.role} · {p.org}
									</span>
								</div>
							</td>
							<td className="n">{p.mood.toFixed(2)}</td>
							<td className="n">
								<span className="mbar" style={{ width: p.cafe * 0.6, background: "var(--tr)" }} />
								{p.cafe.toFixed(1)}%
							</td>
							<td className="n">
								<span className="mbar" style={{ width: p.talk * 1.4, background: "var(--mark)" }} />
								{p.talk.toFixed(1)}%
							</td>
							<td className="n">{p.raised}</td>
							<td className="n">{p.soc.toFixed(2)}</td>
							<td className="n">{p.dil.toFixed(2)}</td>
						</tr>
					))}
				</tbody>
			</table>
		</div>
	);
}

/** Inputs that describe who someone is, as opposed to their situation. */
const WHO = new Set(["temperament", "habit", "person", "client", "customer"]);
const niceInput = (k: string) =>
	({ how_it_was_raised: "how it was raised", effect_on_customer: "effect on customer" })[k] ?? k.replace(/_/g, " ");

/** Main-effect ranges per question set: violet for who, sand for the situation. */
export function Effects({ effects, order }: { effects: Record<string, Record<string, number>>; order: string[] }) {
	return (
		<div className="eff">
			{order
				.filter((q) => effects[q])
				.map((q) => (
					<div className="eff-row" key={q}>
						<div className="eff-q">{q}</div>
						<div className="eff-bars">
							{Object.entries(effects[q] ?? {})
								.sort((a, b) => b[1] - a[1])
								.map(([k, v]) => (
									<div className={`eff-b ${WHO.has(k) ? "e-who" : "e-sit"}`} key={k}>
										<span>{niceInput(k)}</span>
										<span className="t">
											<i style={{ width: `${Math.max(1, v * 100)}%` }} />
										</span>
										<span className="v">{v.toFixed(2)}</span>
									</div>
								))}
						</div>
					</div>
				))}
		</div>
	);
}

export type AnswerRow = { state: Record<string, unknown>; ans: Record<string, unknown>; uses?: number };

type Primary = { label: string; p: number; name?: string };
const num = (v: unknown) => (typeof v === "number" ? v : 0);

/** The one probability that decides a row, whatever shape the question set answers in. */
export function primary(ans: Record<string, unknown>): Primary {
	const [k, v] = Object.entries(ans)[0] ?? ["", 0];
	if (typeof v === "number") return { label: k.replace(/_/g, " "), p: v };
	const d = (v ?? {}) as Record<string, unknown>;
	if (k === "credit") return { label: "any credit", p: 1 - num(d.none) - num(d.other) };
	if (k === "order") return { label: "orders", p: 1 - num(d.none) - num(d.other) };
	if (k === "readiness") return { label: "clean close", p: num(d["2"]) };
	if (k === "queue") {
		const sev = (ans.severity ?? {}) as Record<string, unknown>;
		return { label: "severity: blocked", p: num(sev["2"]) };
	}
	const top = Object.entries(d).sort((x, y) => num(y[1]) - num(x[1]))[0] ?? ["", 0];
	return { label: "most likely", p: num(top[1]), name: top[0] };
}

/**
 * The main-effect range of every input that varies: the widest swing in the
 * deciding probability as that input changes, averaged over the rest. Over
 * the contexts actually sampled, not a controlled design — a ranking.
 */
export function mainEffects(rows: AnswerRow[]): Record<string, number> {
	const out: Record<string, number> = {};
	const keys = Object.keys(rows[0]?.state ?? {});
	for (const k of keys) {
		const groups = new Map<string, number[]>();
		for (const r of rows) {
			const v = JSON.stringify(r.state[k]);
			const list = groups.get(v) ?? [];
			list.push(primary(r.ans).p);
			groups.set(v, list);
		}
		if (groups.size < 2) continue;
		const means = [...groups.values()].map((ps) => ps.reduce((a, b) => a + b, 0) / ps.length);
		out[k] = Math.round((Math.max(...means) - Math.min(...means)) * 1000) / 1000;
	}
	return out;
}

/** Every cached call of one question set: the varying state, and the probability that decides. */
export function AnswerTables({
	tables,
	initial,
	storageKey,
}: {
	tables: Record<string, AnswerRow[]>;
	initial: string;
	storageKey: string;
}) {
	const keys = Object.keys(tables).sort((a, b) => (tables[b]?.length ?? 0) - (tables[a]?.length ?? 0));
	const [sel, setSel] = useState(tables[initial] ? initial : (keys[0] ?? ""));
	useEffect(() => {
		const saved = remembered(storageKey);
		if (saved && tables[saved]) setSel(saved);
	}, [storageKey, tables]);
	const rows = tables[sel] ?? [];
	const varying = Object.keys(rows[0]?.state ?? {}).filter(
		(k) => new Set(rows.map((r) => JSON.stringify(r.state[k]))).size > 1,
	);
	const ranked = rows.map((r) => ({ r, pp: primary(r.ans) })).sort((a, b) => b.pp.p - a.pp.p);
	const withUses = rows.some((r) => r.uses !== undefined);
	const show = (v: unknown) =>
		typeof v === "object" && v !== null ? Object.values(v as Record<string, unknown>).join("; ") : String(v ?? "");
	return (
		<Fig
			title="Jev's answer tables"
			legend={
				<label className="legend" htmlFor="lt-sel">
					question set&nbsp;
					<select
						id="lt-sel"
						value={sel}
						onChange={(e) => {
							setSel(e.target.value);
							remember(storageKey, e.target.value);
						}}
					>
						{keys.map((k) => (
							<option key={k} value={k}>
								{k} ({tables[k]?.length ?? 0})
							</option>
						))}
					</select>
				</label>
			}
			caption="Each row is one cached model call: the parts of the state that vary, and the probability that decides."
			className="mt"
		>
			<div className="tbl tbl-answers">
				<table>
					<thead>
						<tr>
							{varying.map((k) => (
								<th key={k}>{k.replace(/_/g, " ")}</th>
							))}
							{withUses && <th className="n">uses</th>}
							<th>P({ranked[0]?.pp.label ?? ""})</th>
						</tr>
					</thead>
					<tbody>
						{ranked.map(({ r, pp }, i) => (
							// Rows are distinct calls, but two can look alike once the
							// columns that never vary are dropped: the index is the identity.
							<tr key={i}>
								{varying.map((k) => (
									<td className="wrap" key={k}>
										{show(r.state[k])}
									</td>
								))}
								{withUses && <td className="n">{fmt(r.uses ?? 0)}</td>}
								<td>
									<div className="pbar">
										<i style={{ width: `${pp.p * 100}%` }} />
										<span>
											{pp.name ? `${pp.name} ` : ""}
											{pp.p.toFixed(2)}
										</span>
									</div>
								</td>
							</tr>
						))}
					</tbody>
				</table>
			</div>
		</Fig>
	);
}

/** A toggleable legend: click a series to hide it; the last one visible stays. */
export function SeriesToggle({
	series,
	hidden,
	onChange,
}: {
	series: { name: string; color: string }[];
	hidden: Set<string>;
	onChange: (next: Set<string>) => void;
}) {
	return (
		<div className="legend">
			{series.map((s) => (
				<button
					key={s.name}
					type="button"
					aria-pressed={!hidden.has(s.name)}
					onClick={() => {
						const next = new Set(hidden);
						if (next.has(s.name)) next.delete(s.name);
						else next.add(s.name);
						if (next.size < series.length) onChange(next);
					}}
				>
					<Dot color={s.color} />
					{s.name}
				</button>
			))}
		</div>
	);
}

/** The key to Effects: violet inputs are who someone is, sand ones their situation. */
export function WhoLegend() {
	return (
		<div className="legend eff-legend">
			<span>
				<Dot color="--mark" /> who they are
			</span>
			<span>
				<Dot color="--sand" /> the situation
			</span>
		</div>
	);
}

/** The key to the outage dumbbell. */
export function EscLegend() {
	return (
		<div className="legend">
			<span>
				<Dot color="--mark" />
				escalated
			</span>
			<span>
				<Dot color="--dim" />
				not
			</span>
		</div>
	);
}
