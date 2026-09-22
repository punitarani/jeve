"use client";

/**
 * Why an agent did what it did.
 *
 * This is where the research question stops being a claim. A decision row
 * carries the distribution the policy produced *and* the draw taken from it,
 * so you can see both what was thought and what the dice did — and, once Jev
 * is wired in, whether two people in the same situation actually differ.
 */
import { useEffect, useState } from "react";
import type { Decision, Person } from "@jeve/contracts";
import { fetchDecisions, fetchPersons } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import {
	Card,
	CardContent,
	CardHeader,
	CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
	Select,
	SelectContent,
	SelectItem,
	SelectTrigger,
	SelectValue,
} from "@/components/ui/select";
import {
	Table,
	TableBody,
	TableCell,
	TableHead,
	TableHeader,
	TableRow,
} from "@/components/ui/table";
import {
	Tooltip,
	TooltipContent,
	TooltipTrigger,
} from "@/components/ui/tooltip";

export function PersonPanel() {
	const [persons, setPersons] = useState<Person[]>([]);
	const [selected, setSelected] = useState<string | null>(null);
	const [decisions, setDecisions] = useState<Decision[]>([]);
	const [person, setPerson] = useState<Person | null>(null);
	const [error, setError] = useState<string | null>(null);

	useEffect(() => {
		fetchPersons()
			.then((body) => {
				setPersons(body.persons);
				if (body.persons.length > 0 && selected === null) {
					setSelected(body.persons[0]!.id);
				}
			})
			// Swallowing this would leave an empty dropdown with no explanation,
			// which is how a contract mismatch turns into a mystery.
			.catch((e: unknown) => setError(String(e)));
	}, [selected]);

	useEffect(() => {
		if (selected === null) return;
		fetchDecisions(selected)
			.then((body) => {
				setPerson(body.person);
				setDecisions(body.decisions);
				setError(null);
			})
			.catch((e: unknown) => setError(String(e)));
	}, [selected]);

	return (
		<Card size="sm" data-testid="person-panel">
			<CardHeader>
				<CardTitle className="text-xs font-semibold uppercase tracking-widest text-muted-foreground">
					People — what they decided, and how
				</CardTitle>
			</CardHeader>
			<CardContent>
				{error && (
					<p
						className="mb-2.5 text-xs text-destructive"
						data-testid="person-error"
					>
						{error}
					</p>
				)}
				<Select
					items={persons.map((p) => ({
						value: p.id,
						label: `${p.name} — ${p.role} @ ${p.org_id}`,
					}))}
					value={selected}
					onValueChange={(value) => setSelected(value)}
				>
					<SelectTrigger
						className="mb-2.5 w-full"
						data-testid="person-select"
					>
						<SelectValue placeholder="pick someone" />
					</SelectTrigger>
					<SelectContent>
						{persons.map((p) => (
							<SelectItem key={p.id} value={p.id}>
								{p.name} — {p.role} @ {p.org_id}
							</SelectItem>
						))}
					</SelectContent>
				</Select>

				{person?.traits && (
					<p className="muted fineprint">
						traits:{" "}
						{Object.entries(person.traits)
							.map(([k, v]) => `${k} ${v.toFixed(2)}`)
							.join(" · ")}
					</p>
				)}

				{decisions.length === 0 ? (
					<p className="muted" data-testid="no-decisions">
						No decisions recorded yet for this person.
					</p>
				) : (
					<Table data-testid="decision-table">
						<TableHeader>
							<TableRow className="hover:bg-transparent">
								<TableHead className="h-auto px-1.5 py-1 text-xs">
									when
								</TableHead>
								<TableHead className="h-auto px-1.5 py-1 text-xs">
									question
								</TableHead>
								<TableHead className="h-auto px-1.5 py-1 text-xs">by</TableHead>
								<TableHead className="h-auto px-1.5 py-1 text-xs">
									chose
								</TableHead>
								<TableHead className="h-auto px-1.5 py-1 text-xs">
									draw
								</TableHead>
							</TableRow>
						</TableHeader>
						<TableBody>
							{decisions.slice(0, 12).map((d) => {
								const draw = Object.values(d.draws)[0];
								return (
									<TableRow
										key={d.id}
										data-testid="decision-row"
										className="hover:bg-transparent"
									>
										<TableCell className="px-1.5 py-1 text-xs text-muted-foreground">
											{d.label}
										</TableCell>
										<TableCell className="px-1.5 py-1 text-xs">
											{d.question_set}
										</TableCell>
										<TableCell className="px-1.5 py-1 text-xs">
											<Badge variant="outline">{d.source}</Badge>
										</TableCell>
										<TableCell className="px-1.5 py-1 text-xs">
											{summarise(d.chosen)}
										</TableCell>
										<TableCell className="px-1.5 py-1 text-xs">
											{typeof draw === "number" ? (
												<Tooltip>
													<TooltipTrigger
														render={
															<span className="inline-flex cursor-default items-center gap-1.5" />
														}
													>
														<Progress
															value={Math.round(draw * 100)}
															className="w-12 [&_[data-slot=progress-track]]:h-1.5"
														/>
														<span className="text-muted-foreground">
															{draw.toFixed(2)}
														</span>
													</TooltipTrigger>
													<TooltipContent className="font-mono">
														{d.prng_path}
													</TooltipContent>
												</Tooltip>
											) : (
												<span className="muted">—</span>
											)}
										</TableCell>
									</TableRow>
								);
							})}
						</TableBody>
					</Table>
				)}
				<p className="muted fineprint">
					Rules decisions carry a draw but no distribution. Once typed decisions
					are wired in, the distribution appears beside the draw and this table
					answers the project&apos;s actual question.
				</p>
			</CardContent>
		</Card>
	);
}

function summarise(chosen: Record<string, unknown>): string {
	return Object.entries(chosen)
		.filter(([, v]) => v !== null && v !== undefined)
		.map(([k, v]) =>
			typeof v === "boolean" ? (v ? k : `no ${k}`) : `${k}=${v}`,
		)
		.join(", ");
}
