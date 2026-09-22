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
import { toast } from "sonner";
import type { ZodType } from "zod";

import { API, money } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
	Card,
	CardContent,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";

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
					<ScrollArea className="h-full">
						<div className="p-3">
							{agentId !== null ? (
								<AgentPanel id={agentId} tick={status?.tick ?? 0} />
							) : orgId !== null ? (
								<OrgPanel id={orgId} tick={status?.tick ?? 0} />
							) : (
								<Card size="sm" data-testid="world-hint">
									<CardHeader>
										<CardTitle className="text-sm font-normal normal-case tracking-normal">
											Nobody selected
										</CardTitle>
									</CardHeader>
									<CardContent className="text-muted-foreground">
										<p>
											Click a person to see what they last decided and the
											distribution Jev returned for it. Click a building for
											the firm&apos;s books.
										</p>
										<p>
											Grey figures are customers: real demand, drawn as a
											sampled crowd. They are flows, not people with
											positions.
										</p>
									</CardContent>
								</Card>
							)}
						</div>
					</ScrollArea>
				</aside>
			</div>
		</main>
	);
}

function useDetail<T>(path: string, schema: ZodType<T>, tick: number) {
	const [data, setData] = useState<T | null>(null);
	const [error, setError] = useState<string | null>(null);
	useEffect(() => {
		let live = true;
		fetch(`${API}${path}`, { cache: "no-store" })
			.then((r) => (r.ok ? r.json() : Promise.reject(new Error(`${r.status}`))))
			.then((raw) => {
				if (!live) return;
				// safeParse, like lib/api: a shape change is a readable contract
				// error, not a thrown exception three components deep.
				const parsed = schema.safeParse(raw);
				if (parsed.success) {
					setData(parsed.data);
					setError(null);
				} else {
					setError(`${path} did not match the contract`);
				}
			})
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
					<Progress
						value={Math.round(p * 100)}
						className="w-full [&_[data-slot=progress-track]]:h-2 [&_[data-slot=progress-track]]:rounded"
					/>
					<span className="dist-p">{p.toFixed(2)}</span>
				</div>
			))}
		</div>
	);
}

function AgentPanel({ id, tick }: { id: string; tick: number }) {
	const { data, error } = useDetail<Agent>(
		`/world/agents/${encodeURIComponent(id)}`,
		AgentDetail,
		tick,
	);
	if (error !== null)
		return (
			<Card size="sm" className="text-destructive">
				<CardContent>
					Could not load {id}: {error}
				</CardContent>
			</Card>
		);
	if (data === null)
		return (
			<Card size="sm">
				<CardContent className="text-muted-foreground">…</CardContent>
			</Card>
		);
	const d = data.last_decision;
	const color = ORG_PALETTE[data.org_id]?.body ?? "#999";
	return (
		<Card size="sm" data-testid="agent-panel" data-person={data.id}>
			<CardHeader>
				<CardTitle className="text-[15px] font-semibold">
					<span className="swatch" style={{ background: color }} /> {data.name}
				</CardTitle>
				<p className="muted fineprint">
					{data.role.replaceAll("_", " ")} · {data.org_name} ·{" "}
					{data.zone.replaceAll("_", " ")} · {MOODS[data.mood] ?? "—"}
				</p>
			</CardHeader>
			<CardContent>
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
							<Badge variant="outline" data-testid="decided-by">
								{d.source}
							</Badge>{" "}
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
			</CardContent>
		</Card>
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
				toast.error("Could not render dialogue.", {
					description: String(e),
				});
			});
	};

	if (state === "idle" || state === "asking") {
		return (
			<p>
				<Button
					variant="outline"
					size="xs"
					onClick={ask}
					disabled={state === "asking"}
					data-testid="imagine"
					className="text-[var(--mark)]"
				>
					{state === "asking" ? "asking a model…" : "imagine what was said"}
				</Button>
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
		OrgDetail,
		tick,
	);
	if (error !== null)
		return (
			<Card size="sm" className="text-destructive">
				<CardContent>
					Could not load {id}: {error}
				</CardContent>
			</Card>
		);
	if (data === null)
		return (
			<Card size="sm">
				<CardContent className="text-muted-foreground">…</CardContent>
			</Card>
		);
	const color = ORG_PALETTE[data.id]?.body ?? "#999";
	return (
		<Card size="sm" data-testid="org-panel" data-org={data.id}>
			<CardHeader>
				<CardTitle className="text-[15px] font-semibold">
					<span className="swatch" style={{ background: color }} /> {data.name}
				</CardTitle>
				<p className="muted fineprint">{data.kind}</p>
			</CardHeader>
			<CardContent>
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
			</CardContent>
		</Card>
	);
}
