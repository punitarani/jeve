"use client";

import {
	AgentDetail,
	EncounterDialogue,
	ORG_PALETTE,
	OrgDetail,
	type AgentDetail as Agent,
	type EncounterDialogue as Dialogue,
	type OrgDetail as Org,
} from "@jeve/contracts";
import { mountWorld, type WorldStatus } from "@jeve/world";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { API, money } from "@/lib/api";

const MOODS = ["stressed", "flat", "content", "upbeat"];

/** The full-page town: pan, zoom, click a person, click a building. */
export function WorldExplorer() {
	const container = useRef<HTMLDivElement>(null);
	const [status, setStatus] = useState<WorldStatus | null>(null);
	const [agentId, setAgentId] = useState<string | null>(null);
	const [orgId, setOrgId] = useState<string | null>(null);

	useEffect(() => {
		if (container.current === null) return;
		let last = 0;
		const handle = mountWorld(container.current, {
			api: API,
			mode: "explore",
			debug: process.env.NODE_ENV !== "production",
			onSelectAgent: (id) => {
				setAgentId(id);
				if (id !== null) setOrgId(null);
			},
			onSelectBuilding: (id) => {
				setOrgId(id);
				if (id !== null) setAgentId(null);
			},
			onStatus: (next) => {
				const now = performance.now();
				if (now - last > 400) {
					last = now;
					setStatus(next);
				}
			},
		});
		return () => handle.dispose();
	}, []);

	return (
		<main className="world-page">
			<header className="strip">
				<b>jeve</b>
				<span data-testid="world-clock">{status?.label ?? "…"}</span>
				<span className="muted">seq {status?.seq ?? 0}</span>
				<span className="muted">
					{status?.visible ?? 0} of {status?.agents.length ?? 0} staff out
				</span>
				<span className="muted">
					drag to pan · scroll to zoom · click anyone
				</span>
				<Link href="/" className="muted push-right">
					← timeline
				</Link>
			</header>
			<div className="world-body">
				<div
					ref={container}
					className="world-canvas"
					data-testid="world-view"
				/>
				<aside className="world-side">
					{agentId !== null ? (
						<AgentPanel id={agentId} tick={status?.tick ?? 0} />
					) : orgId !== null ? (
						<OrgPanel id={orgId} tick={status?.tick ?? 0} />
					) : (
						<div className="panel" data-testid="world-hint">
							<h3>Nobody selected</h3>
							<p className="muted">
								Click a person to see what they last decided and the
								distribution Jev returned for it. Click a building for the
								firm&apos;s books.
							</p>
							<p className="muted">
								Grey figures are customers: real demand, drawn as a sampled
								crowd. They are flows, not people with positions.
							</p>
						</div>
					)}
				</aside>
			</div>
		</main>
	);
}

function useDetail<T>(path: string, parse: (raw: unknown) => T, tick: number) {
	const [data, setData] = useState<T | null>(null);
	const [error, setError] = useState<string | null>(null);
	useEffect(() => {
		let live = true;
		fetch(`${API}${path}`, { cache: "no-store" })
			.then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
			.then((raw) => live && (setData(parse(raw)), setError(null)))
			.catch((e: unknown) => live && setError(String(e)));
		return () => {
			live = false;
		};
		// Refetched each tick: a panel left open follows the person through the day.
		// eslint-disable-next-line react-hooks/exhaustive-deps
	}, [path, tick]);
	return { data, error };
}

function Bars({
	name,
	dist,
	draw,
}: { name: string; dist: Record<string, number>; draw?: number }) {
	const entries = Object.entries(dist).sort((a, b) => b[1] - a[1]);
	return (
		<div className="dist" data-testid="distribution" data-question={name}>
			<div className="dist-name">
				{name}
				{typeof draw === "number" ? (
					<span className="muted"> · sampled, draw {draw.toFixed(2)}</span>
				) : (
					<span className="muted"> · judged (argmax)</span>
				)}
			</div>
			{entries.map(([option, p]) => (
				<div className="dist-row" key={option} data-testid="distribution-bar">
					<span className="dist-label">
						{name === "mood" ? MOODS[Number(option)] ?? option : option}
					</span>
					<span className="dist-track">
						<span
							className="dist-fill"
							style={{ width: `${Math.round(p * 100)}%` }}
						/>
					</span>
					<span className="dist-p">{p.toFixed(2)}</span>
				</div>
			))}
		</div>
	);
}

function AgentPanel({ id, tick }: { id: string; tick: number }) {
	const { data, error } = useDetail<Agent>(
		`/world/agents/${encodeURIComponent(id)}`,
		(raw) => AgentDetail.parse(raw),
		tick,
	);
	if (error !== null)
		return (
			<div className="panel bad">
				Could not load {id}: {error}
			</div>
		);
	if (data === null) return <div className="panel muted">…</div>;
	const d = data.last_decision;
	const color = ORG_PALETTE[data.org_id]?.body ?? "#999";
	return (
		<div className="panel" data-testid="agent-panel" data-person={data.id}>
			<h3>
				<span className="swatch" style={{ background: color }} /> {data.name}
			</h3>
			<p className="muted">
				{data.role.replaceAll("_", " ")} · {data.org_name} ·{" "}
				{data.zone.replaceAll("_", " ")} · {MOODS[data.mood] ?? "—"}
			</p>
			<h4>Temperament, as Jev is told it</h4>
			<ul className="traits">
				{Object.entries(data.trait_words).map(([trait, words]) => (
					<li key={trait}>
						<span className="muted">
							{trait} {data.traits[trait]?.toFixed(2)}
						</span>{" "}
						{words}
					</li>
				))}
			</ul>
			<h4>Last decision</h4>
			{d === null ? (
				<p className="muted">Has not decided anything yet.</p>
			) : (
				<>
					<p>
						<span className="pill" data-testid="decided-by">
							{d.source}
						</span>{" "}
						<code>{d.question_set}</code>{" "}
						<span className="muted">{d.label}</span>
					</p>
					{d.model !== null && <p className="muted">{d.model}</p>}
					{Object.keys(d.distributions).length === 0 ? (
						<p className="muted">
							Settled by a code rule; no model was asked, so there is no
							distribution to show.
						</p>
					) : (
						Object.entries(d.distributions).map(([name, dist]) => (
							<Bars key={name} name={name} dist={dist} draw={d.draws[name]} />
						))
					)}
					<p className="chosen">
						→{" "}
						{Object.entries(d.chosen)
							.filter(([, v]) => v !== null && v !== false)
							.map(([k, v]) => `${k}=${String(v)}`)
							.join(", ")}
					</p>
				</>
			)}
			<h4>Last encounter</h4>
			{data.last_encounter === null ? (
				<p className="muted">Has not met anyone yet.</p>
			) : (
				<dl className="fields" data-testid="last-encounter">
					<dt>with</dt>
					<dd>{data.last_encounter.with_name}</dd>
					<dt>where</dt>
					<dd>{data.last_encounter.zone.replaceAll("_", " ")}</dd>
					<dt>about</dt>
					<dd>{data.last_encounter.topic.replaceAll("_", " ")}</dd>
					<dt>when</dt>
					<dd>{data.last_encounter.label}</dd>
					<dt>started by</dt>
					<dd>
						{data.last_encounter.initiated
							? data.name
							: data.last_encounter.with_name}
					</dd>
					<dt>led to</dt>
					<dd>
						{data.last_encounter.led_to.length > 0
							? data.last_encounter.led_to.join(", ")
							: "nothing"}
					</dd>
				</dl>
			)}
			{data.last_encounter !== null && (
				<Imagined key={data.last_encounter.seq} seq={data.last_encounter.seq} />
			)}
		</div>
	);
}

/**
 * Prose, on request. The typed fields above are the record; this renders them
 * as a few lines of dialogue for a reader, and the simulation never sees it.
 */
function Imagined({ seq }: { seq: number }) {
	const [state, setState] = useState<"idle" | "asking" | Dialogue>("idle");
	const [error, setError] = useState<string | null>(null);

	// Prose someone already paid for is free to show, so look for it on sight.
	useEffect(() => {
		let live = true;
		fetch(`${API}/encounters/${seq}/dialogue?generate=false`, {
			cache: "no-store",
		})
			.then((r) => r.json())
			.then((raw) => {
				const parsed = EncounterDialogue.parse(raw);
				if (live && parsed.prose !== null) setState(parsed);
			})
			.catch(() => undefined);
		return () => {
			live = false;
		};
	}, [seq]);

	const ask = () => {
		setState("asking");
		setError(null);
		fetch(`${API}/encounters/${seq}/dialogue`, { cache: "no-store" })
			.then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
			.then((raw) => setState(EncounterDialogue.parse(raw)))
			.catch((e: unknown) => {
				setError(String(e));
				setState("idle");
			});
	};

	if (state === "idle" || state === "asking") {
		return (
			<p>
				<button
					type="button"
					className="link-button"
					onClick={ask}
					disabled={state === "asking"}
					data-testid="imagine"
				>
					{state === "asking" ? "asking a model…" : "imagine what was said"}
				</button>
				{error !== null && <span className="bad"> {error}</span>}
			</p>
		);
	}
	if (state.prose === null) {
		return (
			<p className="muted" data-testid="no-prose">
				No prose: {state.reason}. The fields above are the whole record.
			</p>
		);
	}
	return (
		<div className="prose" data-testid="prose">
			{state.prose.lines.map((line, index) => (
				<p key={index}>
					<b>{line.speaker}</b> {line.text}
				</p>
			))}
			<p className="muted prose-note">
				generated by {state.prose.model}
				{state.prose.cached
					? " (cached)"
					: ` for $${state.prose.cost_usd.toFixed(5)}`}{" "}
				· a rendering of the typed record above · not simulation state
			</p>
		</div>
	);
}

function OrgPanel({ id, tick }: { id: string; tick: number }) {
	const { data, error } = useDetail<Org>(
		`/orgs/${encodeURIComponent(id)}`,
		(raw) => OrgDetail.parse(raw),
		tick,
	);
	if (error !== null)
		return (
			<div className="panel bad">
				Could not load {id}: {error}
			</div>
		);
	if (data === null) return <div className="panel muted">…</div>;
	const color = ORG_PALETTE[data.id]?.body ?? "#999";
	return (
		<div className="panel" data-testid="org-panel" data-org={data.id}>
			<h3>
				<span className="swatch" style={{ background: color }} /> {data.name}
			</h3>
			<p className="muted">{data.kind}</p>
			<dl className="fields">
				<dt>cash</dt>
				<dd data-testid="org-cash">{money(data.cash_cents)}</dd>
				<dt>owed to them</dt>
				<dd>{money(data.receivable_cents)}</dd>
				<dt>staff in</dt>
				<dd>
					{data.staff_present} of {data.staff_total}
				</dd>
				<dt>open tickets</dt>
				<dd>{data.open_tickets}</dd>
				<dt>unpaid invoices</dt>
				<dd>{data.unpaid_invoices}</dd>
				<dt>going on</dt>
				<dd>
					{data.active.length > 0 ? data.active.join("; ") : "nothing unusual"}
				</dd>
			</dl>
		</div>
	);
}
