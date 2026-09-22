"use client";

import {
	AgentDetail,
	EncounterDialogue,
	ORG_COLORS,
	OrgDetail,
	type AgentDetail as Agent,
	type EncounterDialogue as Dialogue,
	type OrgDetail as Org,
} from "@jeve/contracts";
import { mountWorld, type WorldHandle, type WorldStatus } from "@jeve/world";
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
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";

const MOODS = ["stressed", "flat", "content", "upbeat"];

/** The level-cut control's value for a cut: "all" for none, else the floor. */
const cutValue = (cut: number | null): string => (cut === null ? "all" : String(cut));

/** Floors are counted from the ground, as a lift button would. */
function floorWord(floor: number): string {
	return floor === 0 ? "ground floor" : `floor ${floor}`;
}

/**
 * Where somebody is, for a caption: a zone is a firm's id, `plaza` or
 * `home` (WORLD-0006), and inside a building the floor says which storey.
 */
function where(zone: string, floor: number): string {
	if (zone === "home") return "at home";
	if (zone === "plaza") return "in the plaza";
	return `at ${zone}, ${floorWord(floor)}`;
}

/** The full-page town: pan, zoom, click a person, click a building. */
export function WorldExplorer() {
	const container = useRef<HTMLDivElement>(null);
	const world = useRef<WorldHandle | null>(null);
	const [status, setStatus] = useState<WorldStatus | null>(null);
	const [agentId, setAgentId] = useState<string | null>(null);
	const [orgId, setOrgId] = useState<string | null>(null);
	// The storey the buildings are cut at (WEB-0007): the model's, mirrored
	// here so the control and the team rows can show it. Null cuts nothing.
	const [cut, setCut] = useState<number | null>(null);
	const applyCut = (next: number | null) => {
		setCut(next);
		world.current?.setLevelCut(next);
	};

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
		world.current = handle;
		return () => {
			world.current = null;
			handle.dispose();
		};
	}, []);

	// A firm's colour, from the map the scene already holds (CORE-0012); the
	// generated roster colour until it has arrived, for a panel opened first.
	const colorOf = (id: string): string =>
		world.current?.paletteOf(id)?.body ?? ORG_COLORS[id] ?? "#999";

	// Highest storey first, as a lift's buttons read, down to the ground; the
	// map says how many there are, so a taller district needs no change here.
	// Read on each status update, which is how the map's arrival reaches it.
	const floors = world.current?.maxFloors() ?? 0;
	const levels = Array.from({ length: Math.max(0, floors - 1) }, (_, i) => floors - 1 - i);

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
				<span className="inline-flex items-center gap-2">
					<span className="muted">cut at</span>
					{/* One pressed item, always: a second press on the pressed one
					    would report an empty value, and is ignored. */}
					<ToggleGroup
						variant="outline"
						size="sm"
						spacing={0}
						value={[cutValue(cut)]}
						onValueChange={(next) => {
							const value = next[0];
							if (value === undefined) return;
							applyCut(value === "all" ? null : Number(value));
						}}
						aria-label="storeys shown"
						data-testid="level-cut"
					>
						<ToggleGroupItem
							value="all"
							className="h-6 px-2 text-[11px] font-normal"
							data-testid="level-cut-all"
						>
							All
						</ToggleGroupItem>
						{levels.map((floor) => (
							<ToggleGroupItem
								key={floor}
								value={String(floor)}
								className="h-6 px-2 text-[11px] font-normal"
								data-testid={`level-cut-${floor}`}
							>
								{floor}
							</ToggleGroupItem>
						))}
						<ToggleGroupItem
							value="0"
							className="h-6 px-2 text-[11px] font-normal"
							data-testid="level-cut-0"
						>
							G
						</ToggleGroupItem>
					</ToggleGroup>
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
								<AgentPanel
									id={agentId}
									tick={status?.tick ?? 0}
									colorOf={colorOf}
								/>
							) : orgId !== null ? (
								<OrgPanel
									id={orgId}
									tick={status?.tick ?? 0}
									cut={cut}
									onPickFloor={applyCut}
								/>
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

function AgentPanel({
	id,
	tick,
	colorOf,
}: {
	id: string;
	tick: number;
	colorOf: (orgId: string) => string;
}) {
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
	const color = colorOf(data.org_id);
	return (
		<Card size="sm" data-testid="agent-panel" data-person={data.id}>
			<CardHeader>
				<CardTitle className="text-[15px] font-semibold">
					<span className="swatch" style={{ background: color }} /> {data.name}
				</CardTitle>
				<p className="muted fineprint" data-testid="agent-where">
					{data.role.replaceAll("_", " ")} · {data.org_name} ·{" "}
					{data.team_name} · {where(data.zone, data.floor)} ·{" "}
					{MOODS[data.mood] ?? "—"}
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

function OrgPanel({
	id,
	tick,
	cut,
	onPickFloor,
}: {
	id: string;
	tick: number;
	cut: number | null;
	onPickFloor: (floor: number | null) => void;
}) {
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
	// The firm's own colours come with its books (CORE-0012).
	const color = data.palette.body;
	return (
		<Card size="sm" data-testid="org-panel" data-org={data.id}>
			<CardHeader>
				<CardTitle className="text-[15px] font-semibold">
					<span className="swatch" style={{ background: color }} /> {data.name}
				</CardTitle>
				<p className="muted fineprint">
					{data.kind} · {data.archetype} ·{" "}
					{data.floors === 1 ? "one floor" : `${data.floors} floors`}
				</p>
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
				<h4>Teams, by floor</h4>
				{/* A team is a floor (WORLD-0006), so a team row is a level cut
				    (WEB-0007): clicking one takes the storeys above it off, and the
				    floor the team works on is the one in view — the same cut as the
				    control in the strip, which follows. Pressed again, it puts the
				    cut back. */}
				<ul className="traits" data-testid="org-teams">
					{data.teams.map((team) => {
						const pressed = cut === team.floor;
						return (
							<li key={team.id} data-testid="org-team" data-floor={team.floor}>
								<button
									type="button"
									aria-pressed={pressed}
									onClick={() => onPickFloor(pressed ? null : team.floor)}
									className="w-full rounded-md px-1.5 py-0.5 text-left hover:bg-muted aria-pressed:bg-muted aria-pressed:text-[var(--mark)]"
								>
									{team.name}{" "}
									<span className="muted">
										{floorWord(team.floor)} · {team.present} of {team.headcount}{" "}
										in
									</span>
								</button>
							</li>
						);
					})}
				</ul>
			</CardContent>
		</Card>
	);
}
